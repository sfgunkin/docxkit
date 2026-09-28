"""A `w:rPr` / `w:pPr` that declares a namespace is still the properties.

The regex registry was founded (2026-08-15, 899 manuscripts) on "no real
document carries an attribute on these elements". Over 3,051 corpus
packages it is false (2026-09-28): `w:rPr` carries one in 3 packages and
`w:pPr` in 7 — every one `xmlns:w`, from a generator that declares the
namespace on the fragments it writes. Each reader below opened the
element as the bare string `<w:rPr>` / `<w:pPr>` and so did not see those
properties at all. Each test reads one shape spelled both ways and asks
for the same answer.
"""
from __future__ import annotations

import pytest

from docxkit import _cite_repair, _compare_read, _tracked_gates, edit, sections

XMLNS = ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SPELLINGS = pytest.mark.parametrize("attrs", ["", XMLNS],
                                    ids=["bare", "xmlns"])


@SPELLINGS
def test_compare_reads_the_formatting_of_a_run_whose_rPr_declares_xmlns(
        attrs):
    """Unread, the bold run read as plain — a formatting difference
    against the same run spelled the other way, which Compare's format
    layer would report on every such run."""
    p = f"<w:p><w:r><w:rPr{attrs}><w:b/></w:rPr><w:t>Bold</w:t></w:r></w:p>"
    plain = "<w:p><w:r><w:t>Bold</w:t></w:r></w:p>"

    text, fmt = _compare_read._char_fmt(p)

    assert text == "Bold"
    assert fmt != _compare_read._char_fmt(plain)[1], "bold is read"
    assert (text, fmt) == _compare_read._char_fmt(p.replace(XMLNS, ""))


@SPELLINGS
def test_sections_reads_a_style_numbering_from_a_pPr_that_declares_xmlns(
        attrs):
    styles = ('<w:styles><w:style w:type="paragraph" w:styleId="H1">'
              f"<w:pPr{attrs}><w:numPr><w:ilvl w:val=\"0\"/>"
              '<w:numId w:val="3"/></w:numPr></w:pPr></w:style></w:styles>')

    numbering, _default = sections._style_numbering(styles)

    assert numbering["H1"] == ("3", "0")


@SPELLINGS
def test_unlinking_leaves_no_EMPTY_rPr_shell_whatever_its_open_tag(attrs):
    """The run's only property was the link style; once it goes, the
    shell goes too. Spelled with xmlns, the shell stayed."""
    span = (f'<w:r><w:rPr{attrs}><w:rStyle w:val="Hyperlink"/></w:rPr>'
            "<w:t>Smith</w:t></w:r>")

    out = edit._plain_runs(span)

    assert out == "<w:r><w:t>Smith</w:t></w:r>"


@SPELLINGS
def test_a_bracket_run_emptied_by_the_repair_is_REMOVED_not_left_blank(
        attrs):
    """The bracket was the run's only character: the run goes, not an
    italic `<w:t></w:t>` shell Word opens and every diff reports."""
    para = ("<w:p><w:r><w:t xml:space=\"preserve\">see </w:t></w:r>"
            f"<w:r><w:rPr{attrs}><w:i/></w:rPr><w:t>(</w:t></w:r>"
            "<w:r><w:t>Smith</w:t></w:r></w:p>")

    out = _cite_repair._delete_char(para, 4, "(", "test")

    assert "<w:i/>" not in out
    assert "(" not in out and "Smith" in out


@SPELLINGS
def test_the_note_space_shape_is_found_with_rPr_on_both_runs(attrs):
    """Compare's `[mark]<del>. </del><r><t>Japan` with run properties on
    the deleted run and the next one — spelled with xmlns, the repair
    did not see the shape and the space stayed lost."""
    xml = ('<w:r><w:footnoteReference w:id="3"/></w:r>'
           '<w:del w:id="10" w:author="W" w:date="2026-09-25T00:00:00Z">'
           f"<w:r><w:rPr{attrs}><w:i/></w:rPr>"
           '<w:delText xml:space="preserve">. </w:delText></w:r></w:del>'
           f"<w:r><w:rPr{attrs}><w:i/></w:rPr><w:t>Japan</w:t></w:r>")

    m = _tracked_gates._NOTE_SPACE_RE.search(xml)

    assert m is not None
    assert m.group(4) == " "
