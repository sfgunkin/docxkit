"""Markdown export: structure survives, nothing is silently dropped."""
from __future__ import annotations

from conftest import dele, ins, make_parts, notes, para, run

from docxkit.export import to_markdown


def p(text: str, *, style: str | None = None, outline: int | None = None
      ) -> str:
    ppr = ""
    if style or outline is not None:
        bits = (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            f'<w:outlineLvl w:val="{outline}"/>' if outline is not None
            else "")
        ppr = f"<w:pPr>{bits}</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def tbl(*rows: tuple[str, ...]) -> str:
    trs = "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p>"
                           "</w:tc>" for c in row) + "</w:tr>"
        for row in rows)
    return f"<w:tbl>{trs}</w:tbl>"


def test_headings_map_by_style_and_outline_level():
    md = to_markdown(make_parts(
        p("The Paper", style="Title")
        + p("Introduction", style="Heading1")
        + p("Data", outline=1)))
    assert "# The Paper\n" in md
    assert "\n# Introduction\n" in md
    assert "\n## Data\n" in md


def test_tables_become_pipe_tables_with_escaped_pipes():
    md = to_markdown(make_parts(tbl(("Country", "A|B"), ("Poland", "1"))))
    assert "| Country | A\\|B |" in md
    assert "|---|---|" in md
    assert "| Poland | 1 |" in md


def test_display_equation_carries_its_number_as_a_tag():
    body = ("<w:p><m:oMath><m:r><m:t>x=y</m:t></m:r></m:oMath>"
            "<w:r><w:t>   (3)</w:t></w:r></w:p>")
    md = to_markdown(make_parts(body))
    assert "$$ x=y \\tag{3} $$" in md


def test_inline_math_stays_in_its_sentence():
    body = ("<w:p><w:r><w:t>where </w:t></w:r>"
            "<m:oMath><m:r><m:t>β</m:t></m:r></m:oMath>"
            "<w:r><w:t> is the slope.</w:t></w:r></w:p>")
    md = to_markdown(make_parts(body))
    assert "where $\\beta$ is the slope." in md


def test_footnote_marker_and_definition():
    body = ('<w:p><w:r><w:t>Claim.</w:t></w:r>'
            '<w:r><w:footnoteReference w:id="2"/></w:r>'
            "<w:r><w:t> More.</w:t></w:r></w:p>")
    notes_xml = ('<w:footnote w:id="2"><w:p><w:r><w:t>The small print.'
             "</w:t></w:r></w:p></w:footnote>")
    md = to_markdown(make_parts(body, footnotes=notes("footnotes", notes_xml)))
    assert "Claim.[^2] More." in md
    assert "[^2]: The small print." in md


def test_captions_are_bolded():
    md = to_markdown(make_parts(p("Table 2. Summary statistics")))
    assert "**Table 2. Summary statistics**" in md


def test_redline_exports_its_final_side_by_default():
    body = para(run("Kept "), ins("added"), dele("dropped"))
    md = to_markdown(make_parts(body))
    assert "Kept added" in md and "dropped" not in md
    original = to_markdown(make_parts(body), view="original")
    assert "dropped" in original and "added" not in original


def test_empty_paragraphs_do_not_produce_blank_bullets():
    md = to_markdown(make_parts(p("One.") + "<w:p/>" + p("Two.")))
    assert "One.\n\nTwo.\n" in md


# --- what the first mutation run found (2026-08-17, 9.3 % survival) -----
#
# Twelve of the eighteen survivors were in `_pipe_table`, ten of them on
# the line that pads a RAGGED row — a table with a merged cell, which
# every real results table has and no fixture here did.

def test_a_RAGGED_row_is_padded_to_the_full_width():
    """A row containing a merged cell is SHORTER than the header, and a
    pipe table whose rows have different column counts renders as
    garbage from that row down — GitHub silently drops the extras and
    pads the shortfall wherever it likes."""
    md = to_markdown(make_parts(tbl(
        ("Country", "50+", "60+"),
        ("Albania", "-0.6", "+1.7"),
        ("Note: one merged cell",))))

    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    assert lines == ["| Country | 50+ | 60+ |",
                     "|---|---|---|",
                     "| Albania | -0.6 | +1.7 |",
                     "| Note: one merged cell |  |  |"]


def test_the_widest_row_sets_the_width_even_when_it_is_not_the_header():
    """A grouped-header table can have a header shorter than its body,
    and sizing from the header alone truncates every data row."""
    md = to_markdown(make_parts(tbl(
        ("Country", "Gap"),
        ("Albania", "-0.6", "+1.7"))))

    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    assert lines == ["| Country | Gap |  |",
                     "|---|---|---|",
                     "| Albania | -0.6 | +1.7 |"]


def test_every_data_row_is_exported_and_the_header_only_once():
    md = to_markdown(make_parts(tbl(
        ("Country", "Value"), ("Albania", "1"), ("Croatia", "2"))))

    assert md.count("| Country | Value |") == 1
    assert "| Albania | 1 |" in md and "| Croatia | 2 |" in md


def test_a_NESTED_table_is_FLATTENED_into_its_cell():
    """`read_all` returns top-level tables only, so a fragment holding
    one is one table however many are inside it, and the nested table's
    text comes along in the cell that holds it — which is what a pipe
    table can carry. (`found[0]` vs `found[-1]` is therefore the same
    table, and that mutant is equivalent as long as this stays true.)"""
    inner = tbl(("inner", "cells"))
    outer = ("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>outer</w:t></w:r></w:p>"
             f"{inner}</w:tc></w:tr></w:tbl>")

    md = to_markdown(make_parts(outer))

    assert md.splitlines()[0] == "| outer inner cells |"


def test_a_paragraph_AFTER_a_table_is_still_exported():
    """`continue`, not `break`: a manuscript's first table arrives long
    before its last paragraph, and stopping there exports the front
    matter and calls it the paper."""
    md = to_markdown(make_parts(tbl(("a", "b")) + p("prose after")))

    assert "prose after" in md


def test_a_BLANK_paragraph_does_not_stop_the_export():
    md = to_markdown(make_parts(p("first") + p("") + p("last")))

    assert "first" in md and "last" in md


def test_TWO_inline_equations_keep_their_own_places():
    """One replacement per marker, in order. Replacing all of them at
    once gives every equation in the sentence the FIRST one's latex —
    and the sentence still reads, which is how it survives review."""
    body = ("<w:p><w:r><w:t>where </w:t></w:r>"
            "<m:oMath><m:r><m:t>a=1</m:t></m:r></m:oMath>"
            "<w:r><w:t> and </w:t></w:r>"
            "<m:oMath><m:r><m:t>b=2</m:t></m:r></m:oMath>"
            "<w:r><w:t> hold.</w:t></w:r></w:p>")

    md = to_markdown(make_parts(body))

    assert "where $a=1$ and $b=2$ hold." in md
