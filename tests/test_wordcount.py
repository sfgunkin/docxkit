"""Word counting into journal-cap buckets.

The fixture is a miniature manuscript with every bucket represented, so
each expected number can be checked by reading the fixture.
"""
from __future__ import annotations

import dataclasses

import pytest
from conftest import dele, ins, make_parts, notes, para, run

from docxkit.wordcount import Counts, count, words


def p(text: str, *, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def tbl(*cells: str) -> str:
    tcs = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>"
                  for c in cells)
    return f"<w:tbl><w:tr>{tcs}</w:tr></w:tbl>"


def equation(tokens: str) -> str:
    return f"<m:oMath><m:r><m:t>{tokens}</m:t></m:r></m:oMath>"


BODY = (
    p("Introduction", style="Heading1")               # headings: 1
    + p("Two plain sentences here.")                  # prose: 4
    + p("Table 1. Summary statistics")                # captions: 4
    + tbl("Country", "Value")                         # tables: 2
    + p("Figure 2 shows one more thing.")             # prose: 6 (mention,
    #                                                   not a caption)
    + p("References")                                 # references: 1
    + p("Author, A. 2020. A cited work.")             # references: 6
    + p("Appendix A. Extra material")                 # appendix: 4
    + p("Three appendix words here.")                 # appendix: 4
    + tbl("appendix", "table", "cells")               # appendix: 3
)


def test_words_is_whitespace_tokens():
    assert words("two  words\nand more") == 4
    assert words("") == 0


def test_every_bucket_lands_where_the_fixture_says():
    counts = count(make_parts(BODY))
    assert counts == Counts(prose=10, headings=1, captions=4, tables=2,
                            references=7, appendix=11)


def test_total_and_exclusions():
    counts = count(make_parts(BODY))
    assert counts.total() == 35
    assert counts.total(exclude=["references", "appendix", "tables",
                                 "captions"]) == 11


def test_unknown_bucket_is_refused():
    with pytest.raises(ValueError, match="unknown bucket"):
        count(make_parts(BODY)).total(exclude=["reference"])  # singular


def test_equations_counted_once_and_separately():
    body = (f"<w:p><w:r><w:t>where </w:t></w:r>{equation('x=y+z')}"
            f"<w:r><w:t> holds.</w:t></w:r></w:p>")
    counts = count(make_parts(body))
    # "where" + "holds." are prose; the math is its own bucket, and the
    # m:t stream must not ALSO be counted as prose via visible_text
    assert (counts.prose, counts.equations) == (2, 1)


def test_footnotes_counted_from_their_own_part():
    notes_xml = ('<w:footnote w:id="0"><w:p><w:r><w:separator/></w:r></w:p>'
             "</w:footnote>"
             '<w:footnote w:id="2"><w:p><w:r><w:t>Four words of note.'
             "</w:t></w:r></w:p></w:footnote>")
    counts = count(make_parts(p("Body."),
                              footnotes=notes("footnotes", notes_xml)))
    assert counts.footnotes == 4


def test_a_redline_counts_its_final_side_by_default():
    body = (f'<w:p>{run("Kept ")}{ins("added pair")}{dele("dropped")}'
            f"</w:p>")
    parts = make_parts(body)
    assert count(parts).prose == 3                       # Kept added pair
    assert count(parts, view="original").prose == 2      # Kept dropped


def test_tables_inside_the_appendix_count_as_appendix():
    counts = count(make_parts(BODY))
    assert counts.appendix == 11        # includes the 3-cell table
    assert counts.tables == 2           # only the main-text table


def test_russian_zone_headings_switch_too():
    body = p("Текст статьи.") + p("Литература") + p("Иванов 2020")
    counts = count(make_parts(body))
    assert (counts.prose, counts.references) == (2, 3)


def test_annex_opens_the_appendix_zone():
    # the World Bank / European heading style — HCW's appendix bucket
    # read zero until "Annex A." was taught to the pattern
    body = p("Body text.") + p("Annex A. Full Regression Results") \
        + p("More annex words here.")
    counts = count(make_parts(body))
    assert (counts.prose, counts.appendix) == (2, 9)


def test_para_fixture_from_conftest_is_compatible():
    # guard against the two test harnesses drifting apart
    counts = count(make_parts(para(run("three plain words"))))
    assert counts.prose == 3


# --- what the first mutation run found (2026-08-17, 28.6 % survival) -----
#
# Twelve of the twenty-eight survivors were the bucket DEFAULTS: nothing
# said an untouched bucket is zero, so `prose: int = 1` passed. The rest
# were the arithmetic inside the zone loop, which the fixture above
# exercises but only through totals that a bitwise slip can reproduce.

def test_an_untouched_bucket_is_ZERO():
    """`Counts()` is what every count starts from, and a default of 1
    would add a word per bucket to every manuscript in the package —
    under a journal cap, silently."""
    assert Counts().as_dict() == {
        "prose": 0, "headings": 0, "captions": 0, "tables": 0,
        "equations": 0, "footnotes": 0, "references": 0, "appendix": 0}
    assert Counts().total() == 0


def test_a_document_with_only_prose_leaves_the_other_buckets_at_zero():
    counts = count(make_parts(p("Four words in prose.")))

    assert counts.as_dict() == {
        "prose": 4, "headings": 0, "captions": 0, "tables": 0,
        "equations": 0, "footnotes": 0, "references": 0, "appendix": 0}


def test_a_count_cannot_be_EDITED_after_it_is_made():
    """Frozen on purpose: a Counts is passed around a paper's test suite
    as the answer, and a bucket assigned to somewhere downstream would
    make the cap check agree with whoever wrote last."""
    counts = count(make_parts(p("Four words in prose.")))

    with pytest.raises(dataclasses.FrozenInstanceError):
        counts.prose = 0            # type: ignore[misc]


def test_a_BLANK_paragraph_does_not_stop_the_count():
    """`continue`, not `break`. Manuscripts are full of blank spacer
    paragraphs, and stopping at the first one would count the opening
    section and call it the paper."""
    body = (p("Four words in prose.") + p(" ")
            + p("Four more words here."))

    assert count(make_parts(body)).prose == 8


def test_a_REFERENCE_entry_counts_its_prose_AND_its_math():
    """`prose + math`, and a bitwise slip reproduces plenty of small
    sums: 5 | 3 is 7, 5 ^ 3 is 6, 5 + 3 is 8. A reference entry carrying
    an equation is unusual; a reference entry carrying a DOI that Word
    typeset as math is not."""
    body = (p("References")
            + '<w:p><w:r><w:t>Author, A. 2020. On five words</w:t></w:r>'
            + equation("x y z") + "</w:p>")

    counts = count(make_parts(body))

    assert counts.references == 1 + 6 + 3
    assert counts.equations == 0        # inside a zone, nothing splits out


def test_a_CAPTION_counts_its_prose_AND_its_math():
    body = ('<w:p><w:r><w:t>Table 1. The elasticity of</w:t></w:r>'
            + equation("a b c") + "</w:p>")

    counts = count(make_parts(body))

    # five and three, not five and two: 5 | 2 and 5 ^ 2 are both 7, so a
    # bitwise slip would read as the right answer
    assert counts.captions == 5 + 3
    assert counts.prose == 0


def test_MAIN_TEXT_math_is_counted_apart_from_the_prose():
    """The one place the two are NOT summed: a journal that excludes
    equations needs them in their own bucket."""
    body = ('<w:p><w:r><w:t>The estimator is</w:t></w:r>'
            + equation("a b c") + "</w:p>")

    counts = count(make_parts(body))

    assert (counts.prose, counts.equations) == (3, 3)
