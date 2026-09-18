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


# --- the cascade, tested where it lives (2026-08-19) -------------------
#
# `Cascade` is styles.py's innermost call — `_compare_read._char_fmt`
# asks it for every run of every paragraph — and the tests that exercise
# its `basedOn` chain live in `tests/test_footnotes.py`, which reads a
# size through it. That file is not in styles.py's harness, so the walk
# came back unasserted in the module's own measurement: the loop guard
# and the group the parent id is read from were both free.


def _cascade(*defs: str) -> Cascade:
    return Cascade(styles_part(*defs).decode("utf-8"))


def _sized(sid: str, half_points: int, *, based_on: str | None = None) -> str:
    base = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    return (f'<w:style w:type="paragraph" w:styleId="{sid}">'
            f'<w:name w:val="{sid}"/>{base}'
            f'<w:rPr><w:sz w:val="{half_points}"/></w:rPr></w:style>')


def _unsized(sid: str, *, based_on: str) -> str:
    return (f'<w:style w:type="paragraph" w:styleId="{sid}">'
            f'<w:name w:val="{sid}"/><w:basedOn w:val="{based_on}"/>'
            "</w:style>")


def test_a_style_INHERITS_from_the_one_it_is_based_on():
    """`self._based[sid] = m.group(1)` — the id inside `w:basedOn`, not
    the whole element. With the element, the next hop looks up
    `'<w:basedOn w:val="Parent"/>'` as a style id, finds nothing, and
    the chain ends one step early: the property reads as unset and the
    caller falls back to the document default."""
    cascade = _cascade(_sized("Parent", 24), _unsized("Child",
                                                      based_on="Parent"))

    assert cascade.resolve("sz", pstyle="Child").value == "24"


def test_a_basedOn_pointing_at_a_MISSING_style_is_not_an_error():
    """`while sid and sid in self._own and …` — all three, in that
    order. A template stripped of a parent style is an ordinary hand-off
    (the journal sends the styles it uses), and under `or` the loop
    enters on a style it has no body for and raises KeyError from inside
    a formatting lookup."""
    cascade = _cascade(_unsized("Orphan", based_on="GoneFromThisFile"))

    assert cascade.resolve("sz", pstyle="Orphan").value is None


def test_a_basedOn_CYCLE_ends_rather_than_hanging():
    """`sid not in seen`: two styles based on each other is a real file
    — Word writes one when a style is renamed into its own parent —
    and the walk has to stop rather than spin."""
    cascade = _cascade(_unsized("A", based_on="B"), _unsized("B",
                                                            based_on="A"))

    assert cascade.resolve("sz", pstyle="A").value is None


def test_a_style_the_document_never_uses_is_not_MISSING():
    """`referenced - defined`, not the symmetric difference. A template
    defines every style the journal has and a paper uses a handful, so
    `^` reports the whole unused remainder as dangling references — and
    a report that lists forty is one nobody reads."""
    parts = make_parts()
    template = dict(TEMPLATE)
    template["word/styles.xml"] = styles_part(
        style("MyEmphasis", "Emphasis", kind="character"),
        style("JnlHeading", "Heading"),
        style("JnlNote", "Note"),
        style("JnlUnusedByThisPaper", "Unused"))

    report = apply_template(parts, template,
                            remap={"MyHeading": "JnlHeading",
                                   "MyNote": "JnlNote"})

    assert report.missing == ["MyTable"]


# --- the run of 2026-08-20: 5.1 %, and the cascade's own reader --------


def test_the_character_style_a_run_NAMES_is_read_out_of_it():
    """`Cascade.style_of` is asked of every run in a comparison — it is
    what makes a hyperlink's underline structural rather than emphasis —
    and its answer is the styleId, not the element that carries it.

    Three mutants lived on those two lines: the whole match instead of
    the captured value, a second group that does not exist, and a guard
    that reads `rpr` when it is EMPTY. The last one is a TypeError the
    moment a run without properties reaches it, which is most runs —
    but not through this module's own tests, where every call had an
    rPr to hand."""
    cascade = Cascade(None)

    assert cascade.style_of(
        '<w:rPr><w:rStyle w:val="Hyperlink"/><w:i/></w:rPr>') == "Hyperlink"
    assert cascade.style_of("<w:rPr><w:i/></w:rPr>") is None
    assert cascade.style_of(None) is None
    assert cascade.style_of("") is None


# --- the run of 2026-09-18: 16.6 %, and the cascade's own readers -----
#
# Five of the seven mutants on `_own_rpr`'s `at == -1` were argued
# EQUIVALENT here until today, and the argument was the shape rule 1 of
# the campaign now names: it spelled out the input that would break it
# ("no WELL-FORMED styles.xml where the cut takes a character a lookup
# needs") and filed the claim anyway. `_own_rpr` is a pure function of a
# string and its contract is one sentence, so the input is a line to
# write rather than a premise to trust. Two of the seven really are
# equivalent and are claimed in tools/equivalents.toml.


def test_a_style_with_no_conditional_BAND_keeps_every_character():
    """The cut is at `w:tblStylePr` and nowhere else. `str.find` answers
    -1 when there is none, and every comparison that is not `== -1`
    slices the body at -1 instead — returning it a character short,
    which is the `>` of its last closing tag."""
    from docxkit.styles import _own_rpr

    body = '<w:name w:val="Body"/><w:rPr><w:i/></w:rPr>'
    banded = (body + '<w:tblStylePr w:type="firstRow">'
              "<w:rPr><w:b/></w:rPr></w:tblStylePr>")

    assert _own_rpr(body) == body
    assert _own_rpr(banded) == body


def _ppr_style(sid: str, ppr: str, *, based_on: str | None = None,
               default: bool = False) -> str:
    """A PARAGRAPH-property style: `w:pPr`, where `_para_style` writes
    `w:rPr`. The cascade reads the two through different doors."""
    base = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    mark = ' w:default="1"' if default else ""
    return (f'<w:style w:type="paragraph"{mark} w:styleId="{sid}">{base}'
            f"<w:pPr>{ppr}</w:pPr></w:style>")


def test_the_attribute_pattern_is_compiled_the_FIRST_time_it_is_asked_for():
    """`_ATTR_RE` is a cache and its fill branch runs once per attribute
    name per PROCESS, so a test asking for a name another test has
    already asked for cannot see this at all. The answer is the
    attribute's VALUE — not the whole `w:hanging="240"` the match spans,
    and not a second group the pattern does not have."""
    from docxkit import styles

    styles._ATTR_RE.pop("hanging", None)
    element = '<w:ind w:left="360" w:hanging="240"/>'

    assert styles._attr_of(element, "hanging") == "240"
    assert "hanging" in styles._ATTR_RE, "the pattern was not kept"
    assert styles._attr_of('<w:ind w:left="360"/>', "hanging") is None


def test_para_element_answers_with_the_WHOLE_element():
    """For the properties whose presence is the whole value. The element
    and not a value: `<w:keepNext/>` states none and means yes."""
    cascade = Cascade(_styles(_ppr_style("Body", "<w:keepNext/>")))

    assert cascade.para_element("keepNext", pstyle="Body") == "<w:keepNext/>"
    assert cascade.para_element("keepLines", pstyle="Body") is None


def test_the_PARAGRAPH_document_default_is_read_apart_from_the_run_one():
    """`w:rPrDefault` holds a `w:spacing` too — the letter spacing of a
    run — so a paragraph asking the whole `w:docDefaults` block for
    "spacing" is answered by that one. The paragraph half is kept
    separately, and it is the last source a paragraph falls back to."""
    styles_xml = (f"<w:styles {NS}><w:docDefaults>"
                  "<w:rPrDefault><w:rPr><w:spacing w:val=\"20\"/></w:rPr>"
                  "</w:rPrDefault>"
                  '<w:pPrDefault><w:pPr><w:spacing w:after="240"/></w:pPr>'
                  "</w:pPrDefault></w:docDefaults></w:styles>")

    assert Cascade(styles_xml).para_attr("spacing", "after") == "240"


def test_a_paragraph_resolves_through_the_style_it_NAMES():
    """And a paragraph that names none through the `w:default="1"` one —
    the two are different sources, and reading the default for a
    paragraph that named a style answers with the wrong one."""
    cascade = Cascade(_styles(_ppr_style("Quote", '<w:ind w:left="720"/>'),
                              _ppr_style("Normal", '<w:ind w:left="0"/>',
                                         default=True)))

    assert cascade.para_attr("ind", "left", pstyle="Quote") == "720"
    assert cascade.para_attr("ind", "left") == "0"


def test_a_paragraph_naming_a_MISSING_style_is_not_an_error():
    """A template stripped of a style is an ordinary hand-off, as it is
    for the run cascade: the walk asks whether the id has a body before
    it reads one."""
    cascade = Cascade(_styles(_ppr_style("Normal", '<w:ind w:left="0"/>')))

    assert cascade.para_attr("ind", "left", pstyle="NoSuchStyle") is None


def test_a_toggle_resolves_through_the_PARAGRAPH_style_too():
    """Word's order for a toggle is the run, the character style, then
    the paragraph style — and for a paragraph naming none, the default
    paragraph style, which is where a manuscript's italics live when a
    whole style is italic."""
    cascade = Cascade(_styles(_para_style("Quote", "<w:i/>")))

    assert cascade.toggle("i", pstyle="Quote") is True
    assert cascade.toggle("b", pstyle="Quote") is False


def test_a_toggle_stated_in_the_document_DEFAULT_is_in_force():
    """The last source, and the one `explain` cannot answer for: a
    toggle's ON form is a bare element with no `w:val` to read."""
    cascade = Cascade(_styles(default="<w:i/>"))

    assert cascade.toggle("i") is True
    assert cascade.toggle("b") is False


def test_a_toggle_through_a_MISSING_style_is_not_an_error():
    cascade = Cascade(_styles(_para_style("Normal", "<w:i/>", default=True)))

    assert cascade.toggle("i", rstyle="NoSuchStyle") is True
