"""The PARAGRAPH layer: indent, spacing, alignment, keep-with-next.

`compare` read run properties and never opened `w:pPr`, so a whole class
of edit passed every layer in silence. Measured 2026-08-29 on
Life_Expectancy's round-1 response letter, where a classifier bug in the
paper's typesetting script gave 7 reference entries body spacing instead
of a hanging indent:

    A (shipped)   spacing=(0, 60, 240)   ind=(left 360, hanging 360)
    B (rebuilt)   spacing=(0, 120, 240)  ind=None

    docxkit compare A B --expect-clean
    REAL change locations (excl. glyph): 0
    EXPECT-CLEAN OK: build matches the user's content

Seven paragraphs of a reference list lost their hanging indent and the
authoritative gate said the documents match.

Resolved through the style cascade, like size and colour and for the
same reason: Word deletes a direct property equal to the inherited one,
so a layer comparing what is STATED reports differences between
documents that render identically — and half this file is about not
doing that. A gate that cries wolf on every rebuild is turned off within
a round, and then it is not a gate.
"""
from __future__ import annotations

import contextlib
import io

import pytest
from conftest import make_parts, write

from docxkit.compare import compare, render

STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<w:styles xmlns:w="http://schemas.openxmlformats.org/'
          'wordprocessingml/2006/main"><w:docDefaults><w:pPrDefault>'
          '<w:pPr><w:spacing w:after="160" w:line="259"/></w:pPr>'
          "</w:pPrDefault><w:rPrDefault><w:rPr>"
          # a letter-spacing default, which is a `w:spacing` too: the
          # paragraph layer must not answer for the RUN default when the
          # paragraph default is the question
          '<w:spacing w:val="20"/><w:sz w:val="24"/></w:rPr>'
          "</w:rPrDefault></w:docDefaults>"
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
          "<w:pPr/></w:style>"
          '<w:style w:type="paragraph" w:styleId="Reference">'
          '<w:pPr><w:spacing w:before="0" w:after="60" w:line="240"/>'
          '<w:ind w:left="360" w:hanging="360"/></w:pPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="RefBased">'
          '<w:basedOn w:val="Reference"/><w:pPr/></w:style>'
          "</w:styles>")

TEXT = ("Ravallion, M. (2016). The Economics of Poverty. "
        "Oxford University Press.")


def _para(ppr: str = "", *, text: str = TEXT) -> str:
    props = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _pair(tmp_path, a_body: str, b_body: str, *, styles: str | None = STYLES):
    """Two documents differing only in what the test is about."""
    extra = {"word/styles.xml": styles} if styles else {}
    return (write(tmp_path / "a.docx", make_parts(a_body, extra=extra)),
            write(tmp_path / "b.docx", make_parts(b_body, extra=extra)))


def _rendered(report) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = render(report, expect_clean=True)
    return code, buf.getvalue()


# ------------------------------------------------- what it must SEE ------


def test_a_reference_list_that_lost_its_hanging_indent_fails_the_gate(
        tmp_path):
    """The measured case, end to end. Every other layer is clean: the
    words are identical, the runs are identical, and until this layer
    existed the report read `REAL change locations: 0`."""
    shipped = _para('<w:spacing w:before="0" w:after="60" w:line="240"/>'
                    '<w:ind w:left="360" w:hanging="360"/>')
    rebuilt = _para('<w:spacing w:before="0" w:after="120" w:line="240"/>')

    report = compare(*_pair(tmp_path, shipped, rebuilt))

    assert report["text"] == [], "the words never moved"
    assert report["format"] == [], "nor the run properties"
    (entry,) = report["paragraph"]
    assert set(entry["from"]) == {"indent left 360", "indent hanging 360",
                                  "spacing after 60"}
    assert entry["to"] == ["spacing after 120"]
    assert entry["context"].startswith("Ravallion")

    code, out = _rendered(report)
    assert code == 1, "--expect-clean must FAIL on it"
    assert "PARAGRAPH" in out and "indent hanging 360" in out


def test_an_alignment_change_is_reported(tmp_path):
    report = compare(*_pair(tmp_path, _para('<w:jc w:val="both"/>'),
                            _para('<w:jc w:val="left"/>')))

    (entry,) = report["paragraph"]
    assert entry["from"] == ["align both"] and entry["to"] == ["align left"]


def test_a_lost_keepNext_is_reported(tmp_path):
    """A caption that stops travelling with its table is a page-break
    defect nobody sees until the PDF, and it is one deleted element."""
    report = compare(*_pair(tmp_path, _para("<w:keepNext/>"), _para()))

    (entry,) = report["paragraph"]
    assert entry["from"] == ["keepNext"] and entry["to"] == []


def test_the_layer_reads_every_PART_a_reader_sees(tmp_path):
    """A footnote's indent is a footnote's indent. The FORMAT layer was
    widened past the body on 2026-08-06 and this one starts there."""
    from conftest import notes

    body = _para()
    note_a = ('<w:footnote w:id="2"><w:p><w:pPr><w:ind w:left="360"/>'
              "</w:pPr><w:r><w:t>A note.</w:t></w:r></w:p></w:footnote>")
    note_b = note_a.replace('w:left="360"', 'w:left="720"')
    extra_a = {"word/styles.xml": STYLES,
               "word/footnotes.xml": notes("footnotes", note_a)}
    extra_b = {"word/styles.xml": STYLES,
               "word/footnotes.xml": notes("footnotes", note_b)}
    a = write(tmp_path / "a.docx", make_parts(body, extra=extra_a))
    b = write(tmp_path / "b.docx", make_parts(body, extra=extra_b))

    (entry,) = compare(a, b)["paragraph"]

    assert entry["part"] == "footnotes"
    assert entry["from"] == ["indent left 360"]


# ----------------------------------------- what it must NOT cry wolf on --


def test_a_value_INHERITED_on_one_side_and_stated_on_the_other_is_equal(
        tmp_path):
    """The reason this resolves rather than reads. Word deletes a direct
    property equal to the inherited one on save, so the same reference
    entry — styled `Reference`, which states the hanging indent — comes
    back from a round-trip with its own copy gone. Both render the same
    page; a stated-value comparison calls it a change every time."""
    states_it = _para('<w:pStyle w:val="Reference"/>'
                      '<w:spacing w:before="0" w:after="60" w:line="240"/>'
                      '<w:ind w:left="360" w:hanging="360"/>')
    inherits_it = _para('<w:pStyle w:val="Reference"/>')

    report = compare(*_pair(tmp_path, states_it, inherits_it))

    assert report["paragraph"] == []
    assert _rendered(report)[0] == 0


def test_a_value_inherited_along_a_basedOn_chain_is_equal(tmp_path):
    """`RefBased` sets nothing and is based on `Reference`. A resolver
    that stopped at the named style would report every paragraph in a
    derived style as having lost the properties it renders with."""
    report = compare(*_pair(tmp_path, _para('<w:pStyle w:val="RefBased"/>'),
                            _para('<w:pStyle w:val="RefBased"/>'
                                  '<w:ind w:left="360" w:hanging="360"/>')))

    assert report["paragraph"] == []


def test_the_strict_and_transitional_spellings_of_an_indent_agree(tmp_path):
    """`w:start`/`w:end` is strict OOXML for `w:left`/`w:right`. A
    document saved by one Word and rebuilt by another renders
    identically, and reporting `indent start 360` -> `indent left 360`
    would be this layer crying wolf on the day it arrived."""
    report = compare(*_pair(tmp_path, _para('<w:ind w:left="360"/>'),
                            _para('<w:ind w:start="360"/>')))

    assert report["paragraph"] == []


def test_one_attribute_stated_directly_KEEPS_the_others_from_the_style(
        tmp_path):
    """Word merges `w:ind` and `w:spacing` attribute by attribute, not
    element by element: a paragraph that states only `before` still gets
    its style's `after` and `line`. Resolved as whole elements, that
    paragraph reads as having lost them — and against the twin that
    states all three it comes back as a difference between two identical
    pages. Found writing this layer, on the first pair that tried it."""
    states_one = _para('<w:spacing w:before="240"/>')
    states_all = _para('<w:spacing w:before="240" w:after="160" '
                       'w:line="259"/>')

    report = compare(*_pair(tmp_path, states_one, states_all))

    assert report["paragraph"] == []


def test_the_paragraph_marks_own_run_spacing_does_not_answer_for_it(
        tmp_path):
    """`w:pPr` nests the paragraph mark's `w:rPr`, and that carries a
    `w:spacing` of its own — the LETTER spacing of a run, which states
    none of `before`/`after`/`line`. A walk that stopped at the first
    `w:spacing` it found would read the paragraph as stating no spacing
    at all and never reach the document default."""
    with_mark = _para('<w:ind w:left="360"/>'
                      '<w:rPr><w:spacing w:val="20"/></w:rPr>')
    without = _para('<w:ind w:left="360"/>')

    report = compare(*_pair(tmp_path, with_mark, without))

    assert report["paragraph"] == []


def test_a_property_stated_as_ZERO_and_one_not_stated_are_the_same_page(
        tmp_path):
    report = compare(*_pair(tmp_path, _para('<w:spacing w:before="0"/>'),
                            _para()))

    assert report["paragraph"] == []


def test_a_toggle_turned_OFF_is_not_a_toggle_turned_on(tmp_path):
    """`<w:keepNext w:val="0"/>` is Word switching an inherited one off.
    Read as presence-means-yes it makes the paragraph that switched it
    off report as the one that switched it on — and then the pair that
    really differs reads as equal."""
    report = compare(*_pair(tmp_path, _para('<w:keepNext w:val="0"/>'),
                            _para()))

    assert report["paragraph"] == []


def test_without_a_styles_part_the_layer_says_nothing(tmp_path):
    """Silence rather than a guess, the same answer the size and colour
    layer gives: with nothing to resolve THROUGH, the redundant-
    declaration case above would report on every round-trip."""
    report = compare(*_pair(tmp_path, _para('<w:ind w:left="360"/>'),
                            _para(), styles=None))

    assert report["paragraph"] == []


def test_the_pPrChange_snapshot_is_not_read_as_the_LIVE_properties(
        tmp_path):
    """A tracked formatting change stores the OLD properties nested
    inside the new ones. Reading the whole blob answers about the past —
    and on a redline against its own clean copy, every tracked
    indent change would then report backwards."""
    tracked = _para('<w:ind w:left="720"/>'
                    '<w:pPrChange w:id="9" w:author="R" w:date="2026-01-01T'
                    '00:00:00Z"><w:pPr><w:ind w:left="360"/></w:pPr>'
                    "</w:pPrChange>")
    plain = _para('<w:ind w:left="720"/>')

    assert compare(*_pair(tmp_path, tracked, plain))["paragraph"] == []


def test_an_EMPTY_paragraph_before_one_does_not_take_its_properties(
        tmp_path):
    """`<w:p w14:paraId="…"/>` is how Word writes an empty paragraph,
    and the comparison's own walk used to swallow it together with the
    paragraph after it — `<w:p[ >]` excludes `<w:pPr` and the bare
    `<w:p/>`, not this. The merged element's first child is another
    `w:p`, so the real paragraph read as stating no properties at all.

    Found on LI5.docx against LI6.docx, whose "References" headings
    carry byte-identical `w:pPr` and were reported as differing."""
    empty = '<w:p w14:paraId="7C02449E" w14:textId="77777777"/>'
    styled = _para('<w:ind w:left="432" w:hanging="432"/>')

    report = compare(*_pair(tmp_path, empty + styled, styled))

    assert report["paragraph"] == [], report["paragraph"]


def test_identical_documents_have_nothing_on_the_layer(tmp_path):
    body = (_para('<w:pStyle w:val="Reference"/>')
            + _para('<w:jc w:val="both"/><w:keepNext/>', text="Second.")
            + _para(text="Third."))

    report = compare(*_pair(tmp_path, body, body))

    assert report["paragraph"] == []
    assert _rendered(report)[0] == 0


# --- the whole sweep of 2026-09-15 ------------------------------------


def test_EVERY_presence_property_is_read_and_not_just_the_first(tmp_path):
    """Four of the seven properties are read by PRESENCE rather than by
    value, and the walk has to reach all four. `keepNext` is the first of
    them, so a walk that stopped there would report a paragraph that lost
    `keepLines`, `pageBreakBefore` and `contextualSpacing` as having lost
    nothing at all — and every one of those three is a page-break
    decision, which shows in the PDF and nowhere else.

    All four on one paragraph, because the walk is per property: the
    tests above take them one at a time, and one at a time is exactly
    what a stop after the first cannot be seen through.
    """
    every = _para("<w:keepNext/><w:keepLines/><w:pageBreakBefore/>"
                  "<w:contextualSpacing/>")

    report = compare(*_pair(tmp_path, every, _para()))

    (entry,) = report["paragraph"]
    assert set(entry["from"]) == {"keepNext", "keepLines", "pageBreakBefore",
                                  "contextualSpacing"}
    assert entry["to"] == []


# --- the DATA census of 2026-09-18 -------------------------------------
#
# Cosmic-ray plans no mutant on a tuple's members or a regex's
# alternatives, so a module whose behaviour lives in data reads as well
# held at any survival rate. Taking each member of `_compare_read`'s data
# out one at a time, 39 of 44 were pinned by the suite; four of the five
# that were not are below. (The fifth, "footer" in `_PART_RANK`, cannot
# change an answer: it is the LAST rank, and a stem that matches nothing
# sorts at `len(_PART_RANK)` — one place further along an order that has
# nothing else in it. `TEXT_PART_RE` admits no stem outside that tuple.)


@pytest.mark.parametrize("off", ["0", "false", "off", "none"])
def test_a_toggle_turned_OFF_reads_as_off_however_Word_spells_it(tmp_path,
                                                                 off):
    """`_OFF` is the set of things OOXML writes for "not on", and three of
    its four members — false, off, none — could be deleted with the whole
    suite green. Only `w:val="0"` was pinned.

    A dropped member reads that spelling as ON, so the paragraph that
    switched `keepNext` OFF is reported as the one that switched it on,
    and the reader is sent to the wrong side of the diff. ST_OnOff admits
    all four spellings and Word has written more than one of them across
    versions, which is why the set holds four.
    """
    turned_off = _para(f'<w:keepNext w:val="{off}"/>')

    report = compare(*_pair(tmp_path, turned_off, _para()))

    assert report["paragraph"] == [], f'w:val="{off}" read as ON'


def test_an_indent_in_the_NEW_attribute_names_is_the_SAME_property(tmp_path):
    """`_ATTR_ALIAS` folds OOXML's `w:start`/`w:end` onto the older
    `w:left`/`w:right`, and the `end` half could be deleted with nothing
    failing.

    Word writes either spelling depending on the version that saved the
    file, so a build and an author copy routinely disagree in spelling
    and agree on the page. Unaliased, "indent end 720" against "indent
    right 720" is a PARAGRAPH difference on a document nobody edited —
    the crying wolf this layer's own docstring says it exists to avoid.
    """
    old = _para('<w:ind w:left="360" w:right="720"/>')
    new = _para('<w:ind w:start="360" w:end="720"/>')

    report = compare(*_pair(tmp_path, old, new))

    assert report["paragraph"] == [], report["paragraph"]
