"""styles — template application with the dangling-reference audit."""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit.errors import PackageError
from docxkit.styles import Cascade, apply_template, ensure, read, used


def style(sid: str, name: str, *, kind: str = "paragraph",
          based_on: str | None = None) -> str:
    base = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    return (f'<w:style w:type="{kind}" w:styleId="{sid}">'
            f'<w:name w:val="{name}"/>{base}</w:style>')


def styles_part(*defs: str) -> bytes:
    return f"<w:styles {NS}>{''.join(defs)}</w:styles>".encode()


def doc_part(body: str) -> bytes:
    return (f"<w:document {NS}><w:body>{body}</w:body></w:document>"
            ).encode()


def make_parts() -> dict[str, bytes]:
    body = ('<w:p><w:pPr><w:pStyle w:val="MyHeading"/></w:pPr>'
            '<w:r><w:rPr><w:rStyle w:val="MyEmphasis"/></w:rPr>'
            "<w:t>x</w:t></w:r></w:p>"
            '<w:tbl><w:tblPr><w:tblStyle w:val="MyTable"/></w:tblPr>'
            "<w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>")
    return {
        "word/document.xml": doc_part(body),
        "word/styles.xml": styles_part(
            style("MyHeading", "My Heading"),
            style("MyEmphasis", "My Emphasis", kind="character"),
            style("MyTable", "My Table", kind="table")),
        "word/footnotes.xml": (
            f'<w:footnotes {NS}><w:footnote w:id="2"><w:p><w:pPr>'
            f'<w:pStyle w:val="MyNote"/></w:pPr></w:p></w:footnote>'
            f"</w:footnotes>").encode(),
    }


TEMPLATE = {"word/styles.xml": styles_part(
    style("JnlHeading", "Journal Heading"),
    style("JnlNote", "Journal Note"),
    style("MyEmphasis", "Emphasis", kind="character"))}


def test_read_parses_id_name_type_and_base():
    styles = read(make_parts())
    by_id = {s.sid: s for s in styles}
    assert by_id["MyHeading"].name == "My Heading"
    assert by_id["MyTable"].type == "table"


def test_used_sees_all_three_reference_kinds():
    xml = make_parts()["word/document.xml"].decode("utf-8")
    assert used(xml) == {"MyHeading", "MyEmphasis", "MyTable"}


def test_apply_template_remaps_and_reports_the_dangling():
    parts = make_parts()
    report = apply_template(parts, TEMPLATE,
                            remap={"MyHeading": "JnlHeading",
                                   "MyNote": "JnlNote"})
    doc = parts["word/document.xml"].decode("utf-8")
    notes = parts["word/footnotes.xml"].decode("utf-8")
    assert 'w:pStyle w:val="JnlHeading"' in doc
    assert 'w:pStyle w:val="JnlNote"' in notes
    assert report.remapped == {"MyHeading": 1, "MyNote": 1}
    # MyEmphasis exists in the template under the same id: not missing.
    # MyTable was neither remapped nor defined: the audit must say so.
    assert report.missing == ["MyTable"]


def test_a_chainable_remap_does_not_chain():
    parts = {
        "word/document.xml": doc_part(
            '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="B"/></w:pPr></w:p>'),
        "word/styles.xml": styles_part(style("A", "a"), style("B", "b")),
    }
    template = {"word/styles.xml": styles_part(style("B", "b"),
                                               style("C", "c"))}
    apply_template(parts, template, remap={"A": "B", "B": "C"})
    doc = parts["word/document.xml"].decode("utf-8")
    assert 'w:val="B"' in doc and 'w:val="C"' in doc


def test_template_without_styles_refuses():
    with pytest.raises(PackageError, match="template"):
        apply_template(make_parts(), {})


def test_ensure_appends_once():
    parts = make_parts()
    new = style("CaptionX", "Caption X")
    assert ensure(parts, new) is True
    assert ensure(parts, new) is False
    assert parts["word/styles.xml"].decode("utf-8").count(
        'w:styleId="CaptionX"') == 1


def test_the_report_reads_when_nothing_was_remapped():
    """`or "none"` — a report of an empty dict said "remapped: " and
    trailed off."""
    parts = make_parts()
    report = apply_template(parts, TEMPLATE)
    assert "none" in report.format()


def test_the_report_names_what_dangles():
    """The `missing` line is the whole point of the audit: every id on it
    is a place the manuscript falls back to Word's defaults. It had no
    test, so neither the branch nor the join that builds it was run."""
    parts = make_parts()
    report = apply_template(parts, TEMPLATE, remap={"MyHeading":
                                                    "JnlHeading"})
    line = report.format()
    assert "MyTable" in line and "MyNote" in line
    assert "UNDEFINED" in line
    assert "MyEmphasis" not in line, "defined in the template: not missing"


def test_the_remap_count_is_per_id_and_counts_every_hit():
    parts = {
        "word/document.xml": doc_part(
            '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr></w:p>'
            '<w:p><w:pPr><w:pStyle w:val="B"/></w:pPr></w:p>'),
        "word/styles.xml": styles_part(style("A", "a"), style("B", "b")),
    }
    report = apply_template(parts, {"word/styles.xml": styles_part(
        style("X", "x"), style("Y", "y"))}, remap={"A": "X", "B": "Y"})
    assert report.remapped == {"A": 2, "B": 1}


# ----------------------------------------------------------- Cascade ----
# What a run's properties RESOLVE to. The mutation sweep found the
# `w:tblStylePr` guard below completely uncovered — a defensive branch
# written against a known trap and never once run.


def _styles(*defs: str, default: str = "") -> str:
    head = (f"<w:docDefaults><w:rPrDefault><w:rPr>{default}"
            f"</w:rPr></w:rPrDefault></w:docDefaults>" if default else "")
    return f"<w:styles {NS}>{head}{''.join(defs)}</w:styles>"


def _para_style(sid: str, rpr: str, based_on: str | None = None,
                default: bool = False) -> str:
    base = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    mark = ' w:default="1"' if default else ""
    return (f'<w:style w:type="paragraph"{mark} w:styleId="{sid}">{base}'
            f"<w:rPr>{rpr}</w:rPr></w:style>")


# The shape every manuscript here has: a default paragraph style that
# states a size, and docDefaults stating a DIFFERENT one.
_NORMAL_24 = _styles(_para_style("Normal", '<w:sz w:val="24"/>', default=True),
                     default='<w:sz w:val="22"/>')


def test_a_paragraph_naming_no_style_is_in_the_default_one():
    """Naming no style is not having none: Word puts such a paragraph in
    the `w:default="1"` style. Resolving it straight to docDefaults
    answers 22 for a paragraph Word renders at 24 — and compares two
    spellings of the same paragraph as a size change (BACKLOG S1)."""
    assert Cascade(_NORMAL_24).of("sz", pstyle=None) == "24"


def test_the_two_spellings_of_the_default_style_resolve_alike():
    """The false-positive half: Word DELETES a direct property equal to
    what it would inherit, so one side of an author round-trip states
    the size and the other does not. Both must resolve the same."""
    cascade = Cascade(_NORMAL_24)
    stated = cascade.of("sz", rpr='<w:rPr><w:sz w:val="24"/></w:rPr>',
                        pstyle=None)
    inherited = cascade.of("sz", rpr="<w:rPr/>", pstyle=None)
    assert stated == inherited == "24"


def test_a_run_that_states_the_document_default_is_not_the_same_as_silence():
    """The silent half, which is why this is S1 and not a cosmetic fix: a
    run stating 22 in an unnamed paragraph really is 11pt among 12pt, and
    resolving both sides to 22 reports a real change clean."""
    cascade = Cascade(_NORMAL_24)
    assert cascade.of("sz", rpr='<w:rPr><w:sz w:val="22"/></w:rPr>',
                      pstyle=None) == "22"
    assert cascade.of("sz", rpr="<w:rPr/>", pstyle=None) == "24"


def test_the_default_style_is_read_whatever_order_its_attributes_are_in():
    marked = ('<w:style w:default="1" w:styleId="Normal" '
              'w:type="paragraph"><w:rPr><w:sz w:val="24"/></w:rPr>'
              "</w:style>")
    cascade = Cascade(_styles(marked, default='<w:sz w:val="22"/>'))
    assert cascade.default_paragraph_style == "Normal"
    assert cascade.of("sz", pstyle=None) == "24"


def test_a_default_CHARACTER_style_is_not_the_paragraph_fallback():
    """`w:default="1"` marks one style per TYPE. Taking the first one
    marked default would put every unnamed paragraph in the default
    character style."""
    char = ('<w:style w:type="character" w:default="1" w:styleId="DefChar">'
            '<w:rPr><w:sz w:val="96"/></w:rPr></w:style>')
    cascade = Cascade(_styles(char, _para_style("Normal",
                                                '<w:sz w:val="24"/>',
                                                default=True),
                              default='<w:sz w:val="22"/>'))
    assert cascade.default_paragraph_style == "Normal"
    assert cascade.of("sz", pstyle=None) == "24"


def test_a_named_style_does_not_fall_back_to_the_default_style():
    """Word's order, and the reason the fallback is on the UNNAMED case
    only: a style that sets nothing inherits along its own basedOn chain
    and then to docDefaults, not through a style it was never based on."""
    cascade = Cascade(_styles(
        _para_style("Normal", '<w:sz w:val="24"/>', default=True),
        _para_style("Quote", '<w:i w:val="1"/>'),
        default='<w:sz w:val="22"/>'))
    assert cascade.of("sz", pstyle="Quote") == "22"


def test_no_default_style_marked_still_falls_to_the_document_default():
    cascade = Cascade(_styles(_para_style("Normal", '<w:sz w:val="24"/>'),
                              default='<w:sz w:val="22"/>'))
    assert cascade.default_paragraph_style is None
    assert cascade.of("sz", pstyle=None) == "22"


def test_a_table_styles_conditional_band_is_not_its_own_properties():
    """A table style nests a whole `w:rPr` per conditional band, AFTER
    its own. Searching the raw element finds the band's — so a style
    whose own rPr is silent would answer with whatever the first-row
    band happens to say."""
    banded = ('<w:style w:type="table" w:styleId="Grid">'
              '<w:rPr><w:sz w:val="20"/></w:rPr>'
              '<w:tblStylePr w:type="firstRow"><w:rPr>'
              '<w:sz w:val="96"/></w:rPr></w:tblStylePr></w:style>')
    assert Cascade(_styles(banded)).of("sz", pstyle="Grid") == "20"


def test_a_band_is_not_borrowed_when_the_style_itself_is_silent():
    """The half that fails LOUDLY without the cut: nothing of the
    style's own to find, so the band's 48pt is what comes back."""
    silent = ('<w:style w:type="table" w:styleId="Grid">'
              '<w:tblStylePr w:type="firstRow"><w:rPr>'
              '<w:sz w:val="96"/></w:rPr></w:tblStylePr></w:style>')
    cascade = Cascade(_styles(silent, default='<w:sz w:val="24"/>'))
    assert cascade.of("sz", pstyle="Grid") == "24", "took the band's size"


def test_known_is_true_with_only_document_defaults():
    """`known` gates the whole size/colour comparison in `compare`. Read
    with `and` instead of `or` it goes quietly False on a package that
    has one source and not the other, and the layer stops looking
    without saying so."""
    assert Cascade(_styles(default='<w:sz w:val="24"/>')).known is True


def test_known_is_true_with_only_style_definitions():
    assert Cascade(_styles(_para_style("N", '<w:sz w:val="20"/>'))).known


def test_known_is_false_with_no_styles_part():
    assert Cascade().known is False
    assert Cascade("").known is False


def test_paragraph_style_reads_off_an_instance_too():
    """It is a @staticmethod, and callers here reach it through the
    class. Removing the decorator leaves that working and breaks the
    instance call, which is the one a reader would write."""
    p = '<w:p><w:pPr><w:pStyle w:val="Note"/></w:pPr></w:p>'
    assert Cascade().paragraph_style(p) == "Note"
    assert Cascade.paragraph_style(p) == "Note"


def test_a_package_missing_a_referring_part_keeps_going():
    """`continue`, not `break`: a document with no footnotes must not
    stop the walk before comments."""
    parts = {
        "word/document.xml": doc_part(
            '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr></w:p>'),
        "word/comments.xml": (
            f'<w:comments {NS}><w:comment w:id="1"><w:p><w:pPr>'
            f'<w:pStyle w:val="A"/></w:pPr></w:p></w:comment>'
            f"</w:comments>").encode(),
        "word/styles.xml": styles_part(style("A", "a")),
    }
    report = apply_template(parts, {"word/styles.xml": styles_part(
        style("X", "x"))}, remap={"A": "X"})
    assert report.remapped == {"A": 2}, "the comments part was skipped"


# ------------------------------------------------- the resolution cache --

def test_resolve_is_memoised_and_keyed_on_everything_it_reads():
    """`Cascade.of` is the innermost call in the package: `_char_fmt`
    asks for several properties of every RUN, and it was 43 % of
    `compare.load` (278 ms against the 34 ms the comparison itself took,
    LI7 prev -> working). A Cascade never changes after construction, so
    the answer is worth keeping — as long as the key holds everything
    the answer depends on."""
    from docxkit.styles import Cascade

    styles = (
        '<w:styles><w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:rPr><w:sz w:val="24"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Quote">'
        '<w:rPr><w:sz w:val="20"/></w:rPr></w:style></w:styles>')
    c = Cascade(styles)

    first = c.resolve("sz", pstyle="Quote")
    again = c.resolve("sz", pstyle="Quote")
    assert first.value == "20"
    assert again is first, "the second lookup rebuilt the answer"

    # every part of the key changes the answer, so every part must be IN it
    assert c.resolve("sz", pstyle=None).value == "24"      # default style
    assert c.resolve("sz", rstyle="Quote", pstyle=None).value == "20"
    assert c.resolve("sz", rpr='<w:sz w:val="18"/>').value == "18"
    assert c.resolve("szCs", pstyle="Quote").value is None
