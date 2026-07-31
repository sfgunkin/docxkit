"""Word counting into journal-cap buckets.

The fixture is a miniature manuscript with every bucket represented, so
each expected number can be checked by reading the fixture.
"""
from __future__ import annotations

import pytest
from conftest import NS, dele, ins, para, run

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


def make_parts(body: str, *, footnotes: str | None = None
               ) -> dict[str, bytes]:
    parts = {"word/document.xml":
             f"<w:document {NS}><w:body>{body}</w:body></w:document>"
             .encode()}
    if footnotes is not None:
        parts["word/footnotes.xml"] = (
            f"<w:footnotes {NS}>{footnotes}</w:footnotes>").encode()
    return parts


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
    notes = ('<w:footnote w:id="0"><w:p><w:r><w:separator/></w:r></w:p>'
             "</w:footnote>"
             '<w:footnote w:id="2"><w:p><w:r><w:t>Four words of note.'
             "</w:t></w:r></w:p></w:footnote>")
    counts = count(make_parts(p("Body."), footnotes=notes))
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


def test_para_fixture_from_conftest_is_compatible():
    # guard against the two test harnesses drifting apart
    counts = count(make_parts(para(run("three plain words"))))
    assert counts.prose == 3
