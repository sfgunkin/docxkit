r"""`prose_props` and `para` are documented as a pair; their shapes were not.

Measured on Parental_style, 2026-09-01, building a supplemental file.
`prose_props(title_xml)` returned the rPr WITH its wrapper and the pPr
WITHOUT, and `para(run(text, rpr), ppr)` splices its argument in
verbatim — so the composition the skill's own example shows wrote

    <w:p><w:spacing …/><w:jc w:val="center"/>…<w:r>

a paragraph whose "properties" are bare children of `w:p`. Word keeps
the runs and DISCARDS the schema-invalid children without a word: four
title-block paragraphs shipped left-aligned at 16pt, and `lint` passed
the file. It was found by rasterising the PDF and looking.

Three changes, and each is tested here. `prose_props` returns the
wrapper, so the pair is symmetric. `para` normalises either spelling, so
a caller that already wraps — the paper's `_wrapped_ppr` workaround did
— is not punished for it. And `lint` refuses the shape, which is the
check that catches it whatever wrote the paragraph.
"""
from __future__ import annotations

from conftest import make_parts

from docxkit.body import para, prose_props, run
from docxkit.lint import lint_parts

STYLED = ('<w:p><w:pPr><w:spacing w:line="240" w:lineRule="auto"/>'
          '<w:jc w:val="center"/></w:pPr>'
          '<w:r><w:rPr><w:sz w:val="32"/></w:rPr>'
          "<w:t>A Supplemental Title</w:t></w:r></w:p>")


# ------------------------------------------------------- the two shapes


def test_both_halves_come_back_WRAPPED():
    ppr, rpr = prose_props(STYLED)

    assert ppr.startswith("<w:pPr>") and ppr.endswith("</w:pPr>")
    assert rpr.startswith("<w:rPr>") and rpr.endswith("</w:rPr>")


def test_the_documented_composition_produces_a_valid_paragraph():
    """`para(run(text, rpr), ppr)` — the skill's own example, and what
    wrote the left-aligned title block."""
    ppr, rpr = prose_props(STYLED)

    built = para(run("A Supplemental Title", rpr), ppr)

    assert built.startswith("<w:p><w:pPr>"), built
    assert built.count("<w:pPr>") == 1, "not wrapped twice"
    assert lint_parts(make_parts(built)) == []


def test_para_accepts_a_ppr_that_is_ALREADY_wrapped():
    """The paper's workaround wraps before calling. Double-wrapping it
    now would punish the caller who worked around the defect."""
    built = para(run("x"), '<w:pPr><w:jc w:val="center"/></w:pPr>')

    assert built.count("<w:pPr>") == 1
    assert lint_parts(make_parts(built)) == []


def test_para_still_wraps_a_BARE_ppr():
    """Every caller written against the old shape keeps working, and
    produces valid XML now instead of silently-dropped children."""
    built = para(run("x"), '<w:jc w:val="center"/>')

    assert built == ('<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
                     "<w:r><w:t>x</w:t></w:r></w:p>")


def test_no_properties_stays_no_properties():
    assert para(run("x")) == "<w:p><w:r><w:t>x</w:t></w:r></w:p>"


# ------------------------------------------------------------ the gate


def test_lint_refuses_a_paragraph_property_outside_its_pPr():
    """The check that would have caught it whatever built the file."""
    stray = ('<w:p><w:jc w:val="center"/>'
             "<w:r><w:t>A Supplemental Title</w:t></w:r></w:p>")

    problems = lint_parts(make_parts(stray))

    assert problems, "Word drops this silently; something has to say so"
    assert "w:jc sits directly in w:p" in problems[0]
    assert "drops it silently" in problems[0]


def test_the_paragraph_MARK_run_properties_are_not_a_stray():
    """`w:rPr` IS legal directly in a `w:p` — it is the paragraph mark's
    own run properties, which every tracked paragraph-mark revision
    carries. Listing it would fail every redline in the corpus."""
    mark = ('<w:p><w:pPr><w:rPr><w:ins w:id="7" w:author="R" '
            'w:date="2026-01-01T00:00:00Z"/></w:rPr></w:pPr>'
            "<w:r><w:t>tail</w:t></w:r></w:p>")

    assert lint_parts(make_parts(mark)) == []


def test_a_properly_wrapped_paragraph_is_clean():
    assert lint_parts(make_parts(STYLED)) == []
