"""The branches of `edit` that the callers never happened to produce.

A cosmic-ray pass over `edit.py` (849 mutants, 191 survivors) put its
biggest cluster — 22 mutants on ONE line — on the italics-OFF branch of
`_run_italic`, and coverage agreed: line 213 was never executed by any
test in the suite. The rest of the survivors sat on the same four
uncovered lines and on arithmetic whose result nothing asserted
precisely enough to notice it changing.

These are the paths a manuscript reaches and the fixtures did not: a run
that states italics OFF rather than omitting them, a `w:space` in the
wrong namespace, an anchor matched through Word's glyph substitutions,
and a replacement that ends in the middle of a run.
"""
from __future__ import annotations

import pytest

from docxkit._xml import RUN_RE, visible_text
from docxkit.edit import italicize, preserve_space, replace_in_para, subscript
from docxkit.errors import AnchorError


def para(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def run(text: str, *, rpr: str = "") -> str:
    return f"<w:r>{rpr}<w:t>{text}</w:t></w:r>"


# ------------------------------------------------ italics stated OFF ----
# `<w:i w:val="0"/>` is not the same as no `w:i` at all: Word writes it
# when a style says italic and this run overrides it back to upright.


@pytest.mark.parametrize("off", ['<w:i w:val="0"/>', '<w:i w:val="false"/>',
                                 '<w:i w:val="none"/>'])
def test_a_run_that_states_italics_off_is_turned_on_in_place(off):
    """The off tag is REPLACED. Appending `<w:i/>` beside it leaves two
    `w:i` elements in one `w:rPr`, which is schema-invalid, and leaves
    Word to pick — it picks the last, so the run stays upright."""
    p = para(run("word", rpr=f"<w:rPr>{off}</w:rPr>"))
    got = italicize(p, "word")
    assert "<w:i/>" in got
    assert 'w:val="0"' not in got and 'w:val="false"' not in got
    assert got.count("<w:i") == 1


def test_the_off_tag_is_replaced_where_it_stood_not_appended():
    """Schema order: `w:i` sits between `w:b` and `w:sz`, and the off tag
    was already in the right place."""
    p = para(run("word", rpr=('<w:rPr><w:b/><w:i w:val="0"/>'
                              '<w:sz w:val="20"/></w:rPr>')))
    got = italicize(p, "word")
    assert "<w:rPr><w:b/><w:i/><w:sz w:val=\"20\"/></w:rPr>" in got


def test_a_run_already_italic_is_left_exactly_as_it_was():
    p = para(run("word", rpr="<w:rPr><w:i/></w:rPr>"))
    assert italicize(p, "word") == p


# ------------------------------------- a w:space in the wrong namespace --


def test_a_wrong_namespace_space_attribute_is_stripped_and_counted():
    """`w:space="preserve"` is a no-op Word ignores — but it LOOKS like
    protection, so it can mask an edge space that is not protected at
    all. Stripping it is the point; the count is how a build reports it.
    """
    p = para('<w:r><w:t w:space="preserve">clean</w:t></w:r>')
    got, fixed = preserve_space(p)
    assert 'w:space="preserve"' not in got
    assert "<w:t>clean</w:t>" in got
    assert fixed == 1


def test_a_wrong_namespace_space_beside_a_real_edge_space_gets_both():
    p = para('<w:r><w:t w:space="preserve">trailing </w:t></w:r>')
    got, fixed = preserve_space(p)
    assert '<w:t xml:space="preserve">trailing </w:t>' in got
    assert got.count("space=") == 1         # the junk one is gone
    assert fixed == 1


def test_a_run_already_correctly_protected_is_not_counted_again():
    p = para('<w:r><w:t xml:space="preserve"> x </w:t></w:r>')
    got, fixed = preserve_space(p)
    assert got == p and fixed == 0


# ------------------------------------------ matching through the glyphs --


def test_a_style_anchor_matches_through_a_curly_apostrophe():
    """`_locate(normalize=True)` — the path `_hits` takes for a manuscript
    where autocorrect ran on some paragraphs and not others. Never
    executed by any test, so every mutation of it survived."""
    p = para(run("workers’ pay rose"))
    got = italicize(p, "workers' pay", normalize=True)
    assert "<w:i/>" in got
    # the document keeps ITS glyph; only the match was normalised
    assert "’" in got
    assert visible_text(got) == "workers’ pay rose"


def test_a_normalized_anchor_that_is_absent_still_refuses():
    p = para(run("workers’ pay"))
    with pytest.raises(AnchorError, match="not in"):
        italicize(p, "managers' pay", normalize=True)


def test_replace_in_para_refuses_an_absent_normalized_anchor():
    p = para(run("workers’ pay"))
    with pytest.raises(AnchorError, match="not in paragraph"):
        replace_in_para(p, "managers' pay", "x", normalize=True)


# -------------------------------------------- one match, and only one ----


def test_an_anchor_that_occurs_twice_is_refused():
    """Silence here is the dangerous outcome: replacing the first of two
    is a build that keeps succeeding while editing the wrong sentence."""
    p = para(run("ab and ab"))
    with pytest.raises(AnchorError, match="occurs twice"):
        replace_in_para(p, "ab", "zz")


def test_the_second_occurrence_is_found_even_when_it_overlaps_the_first():
    p = para(run("aaa"))
    with pytest.raises(AnchorError, match="occurs twice"):
        replace_in_para(p, "aa", "z")


# ----------------------------------------- a replacement that ends mid-run


def test_a_replacement_spanning_runs_keeps_the_tail_of_the_last_one():
    """`tail = body[end - start:]`. Get that offset wrong and the text
    AFTER the match is deleted — silently, because the replacement
    itself still lands correctly."""
    p = para(run("Hello wo"), run("rld and more"))
    got = replace_in_para(p, "world", "planet")
    assert visible_text(got) == "Hello planet and more"


def test_a_replacement_inside_one_run_keeps_both_sides():
    p = para(run("Hello world and more"))
    got = replace_in_para(p, "world", "planet")
    assert visible_text(got) == "Hello planet and more"


def test_a_replacement_covering_three_runs_keeps_the_outer_text():
    p = para(run("keep A"), run("BBB"), run("C keep"))
    got = replace_in_para(p, "ABBBC", "x")
    assert visible_text(got) == "keep x keep"


# ------------------------------------------- styling part of one run ----


def styled_runs(xml: str, marker: str) -> list[str]:
    """The visible text of each run carrying `marker` — which is the
    question these tests are actually asking, and asking it by string
    order got the answer right for the wrong reason."""
    return [visible_text(m.group(0)) for m in RUN_RE.finditer(xml)
            if marker in m.group(0)]


def test_styling_a_prefix_leaves_the_rest_of_the_run_alone():
    """`if lo == 0 and hi == len(body)` — with `or` there, a span that
    merely STARTS at a run boundary takes the whole-run path and styles
    text nobody asked for."""
    p = para(run("abcdef"))
    got = italicize(p, "abc")
    assert visible_text(got) == "abcdef"
    assert styled_runs(got, "<w:i/>") == ["abc"]


def test_styling_a_suffix_leaves_the_head_alone():
    p = para(run("abcdef"))
    got = subscript(p, "def")
    assert visible_text(got) == "abcdef"
    assert styled_runs(got, "<w:vertAlign") == ["def"]


def test_styling_the_middle_leaves_both_sides_alone():
    p = para(run("abcdef"))
    got = italicize(p, "cd")
    assert visible_text(got) == "abcdef"
    assert styled_runs(got, "<w:i/>") == ["cd"]


def test_styling_a_whole_run_does_not_split_it():
    p = para(run("abc"), run("def"))
    got = italicize(p, "abc")
    assert visible_text(got) == "abcdef"
    assert got.count("<w:t>") == 2          # no split was needed
