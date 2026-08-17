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
