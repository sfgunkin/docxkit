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
from conftest import field

from docxkit._xml import RUN_RE, internal_links, visible_text
from docxkit.edit import (
    _links_to,
    find_normalized,
    italicize,
    preserve_space,
    relabel_link,
    remove_link,
    remove_links,
    rep,
    replace_in_para,
    subscript,
)
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


def test_the_edit_facade_exports_both_run_patterns():
    """`RUN_RE` is how a caller walks whole `w:r` elements, which is what
    run-aware surgery needs, and it sat next to `T_RUN_RE` unexported --
    so pyright rejected the import while its sibling came in clean.

    Hand-rolling the pattern instead is the trap it exists to prevent:
    `rfind("<w:r")` also matches `<w:rPr`, which on Parental_style
    spliced a paragraph mid-properties and destroyed an equation label
    two screens away. `<w:r\b` is exactly that guard.
    """
    import docxkit.edit as E
    for name in ("RUN_RE", "T_RUN_RE"):
        assert name in E.__all__, f"{name} is not exported"
        assert hasattr(E, name)
    assert E.RUN_RE.match("<w:r><w:t>x</w:t></w:r>")
    assert not E.RUN_RE.match("<w:rPr><w:b/></w:rPr>")


# --- the safe run-properties sweep (BACKLOG S4, 2026-08-20) ------------


def _field_caption() -> str:
    """AFI's Figure 10 caption: the number is a field-code hyperlink."""
    return ('<w:p><w:r><w:t xml:space="preserve">Figure 10. </w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText> HYPERLINK "
            + chr(92) + 'l "fig10_firstref" </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            "<w:r><w:t>Employment by age group</w:t></w:r>"
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


HOUSE = {"rFonts": '<w:rFonts w:ascii="Arial Narrow"/>',
         "sz": '<w:sz w:val="20"/>'}


def test_a_sweep_writes_the_face_and_leaves_the_field_MACHINERY_alone():
    """The whole point of the helper. A sweep that walks `<w:r>` writes
    into the `fldChar` and `instrText` runs too — they are runs — and
    Word's Compare then marks every one of them. Rejecting that batch
    brings the words back as plain text with the anchor gone.

    The field's LABEL is not machinery: it is what the page shows, and a
    caption whose number lives inside a field still wants the face the
    rest of the caption has."""
    from docxkit.edit import set_run_properties

    out, written = set_run_properties(_field_caption(), HOUSE)

    assert written == 2, "the caption's own run and the field's label"
    assert out.count('w:ascii="Arial Narrow"') == 2
    assert "<w:rPr>" not in out[out.index("<w:fldChar"):out.index(
        "separate")], "nothing was written into the machinery"
    assert "fig10_firstref" in out


def test_the_sweep_COUNTS_the_runs_it_changed_not_the_ones_it_visited():
    """A second pass over the same paragraph reports 0. The count is
    what a caller prints, and one that answers "24 runs" every time it
    runs says nothing about whether anything moved."""
    from docxkit.edit import set_run_properties

    once, first = set_run_properties(_field_caption(), HOUSE)
    twice, again = set_run_properties(once, HOUSE)

    assert (first, again) == (2, 0)
    assert twice == once


def test_the_sweep_can_be_told_to_write_into_the_field_runs():
    """`skip_fields=False` is the behaviour this helper exists to
    replace, kept reachable and named so a caller who wants it says
    so."""
    from docxkit.edit import set_run_properties

    _out, written = set_run_properties(_field_caption(), HOUSE,
                                       skip_fields=False)

    assert written == 6, "every run in the paragraph"


def test_a_field_run_is_one_with_MACHINERY_and_no_text():
    """Both halves. A run holding an `instrText` is machinery; a run
    holding the field's result is not, even though it sits inside the
    same field."""
    from docxkit.edit import is_field_run

    assert is_field_run('<w:r><w:fldChar w:fldCharType="begin"/></w:r>')
    assert is_field_run("<w:r><w:instrText> PAGE </w:instrText></w:r>")
    assert not is_field_run("<w:r><w:t>Employment</w:t></w:r>")
    # a fldChar and a stray label in ONE run: an edit across a field
    # leaves exactly this, and it is text a reader sees
    assert not is_field_run('<w:r><w:fldChar w:fldCharType="begin"/>'
                            "<w:t>leftover</w:t></w:r>")


def test_the_sweep_writes_into_the_LIVE_properties():
    """Through `set_run_property`, so a tracked formatting change keeps
    its snapshot and the page gets the face."""
    from docxkit.edit import set_run_properties

    date = 'w:id="7" w:author="A" w:date="2026-01-01T00:00:00Z"'
    para_xml = (f'<w:p><w:r><w:rPr><w:sz w:val="24"/><w:rPrChange {date}>'
                f'<w:rPr><w:sz w:val="28"/></w:rPr></w:rPrChange></w:rPr>'
                f"<w:t>Text</w:t></w:r></w:p>")

    out, written = set_run_properties(para_xml, {"sz": '<w:sz w:val="20"/>'})

    live, _, past = out.partition("<w:rPrChange")
    assert written == 1
    assert '<w:sz w:val="20"/>' in live and '<w:sz w:val="24"/>' not in live
    assert '<w:sz w:val="28"/>' in past, "the past stands"


def test_a_property_can_be_REMOVED_by_the_sweep():
    from docxkit.edit import set_run_properties

    para_xml = ('<w:p><w:r><w:rPr><w:b/><w:sz w:val="24"/></w:rPr>'
                "<w:t>Text</w:t></w:r></w:p>")

    out, written = set_run_properties(para_xml, {"b": ""})

    assert written == 1
    assert "<w:b/>" not in out and '<w:sz w:val="24"/>' in out


def test_italics_ON_takes_out_EVERY_stale_copy():
    """The seventh writer of the shape this package spent 2026-08-20
    on: `w:i` twice in one `w:rPr` is invalid and does happen — a style
    states it OFF and a writer that could not see that put a second one
    beside it. Replacing the first leaves the stale element sorting
    ahead of the new one, which is the reading Word takes, so a
    reference entry `refstyle` reported as re-italicised came back
    roman.

    The pairs below are the two orders a document produces them in."""
    from docxkit.edit import italicize

    def para_xml(props: str) -> str:
        return (f"<w:p><w:r><w:rPr>{props}</w:rPr>"
                "<w:t>Journal of Economics</w:t></w:r></w:p>")

    for props in ('<w:i w:val="0"/><w:i w:val="0"/>',
                  '<w:i w:val="0"/><w:i/>',
                  '<w:i/><w:i w:val="0"/>'):
        out = italicize(para_xml(props), "Journal of Economics")
        assert out == para_xml("<w:i/>"), props

    # and a property AFTER the pair, which is what tells the write from
    # the removal: cut at the LAST copy's end and the size goes with it
    out = italicize(para_xml('<w:i w:val="0"/><w:i w:val="0"/>'
                             '<w:sz w:val="20"/>'),
                    "Journal of Economics")
    assert out == para_xml('<w:i/><w:sz w:val="20"/>')


def test_a_run_already_italic_is_still_handed_back_untouched():
    """The other side of that branch, and the reason it cannot simply
    normalise every run it meets: an italic run is not a change, and a
    writer that rewrites it puts a revision in the document."""
    from docxkit.edit import italicize

    for props in ("<w:i/>", "<w:i></w:i>"):
        para_xml = (f"<w:p><w:r><w:rPr>{props}</w:rPr>"
                    "<w:t>Journal</w:t></w:r></w:p>")
        assert italicize(para_xml, "Journal") == para_xml, props


def test_a_second_vertAlign_comes_out_with_the_first():
    """`w:vertAlign` twice, the same shape one function down. The stale
    `baseline` left beside a new `subscript` is a subscript Word may
    render flat."""
    from docxkit.edit import subscript

    para_xml = ('<w:p><w:r><w:rPr><w:sz w:val="20"/>'
                '<w:vertAlign w:val="superscript"/>'
                '<w:vertAlign w:val="baseline"/>'
                '<w:lang w:val="en-US"/></w:rPr>'
                "<w:t>t</w:t></w:r></w:p>")

    out = subscript(para_xml, "t")

    assert out == ('<w:p><w:r><w:rPr><w:sz w:val="20"/>'
                   '<w:vertAlign w:val="subscript"/>'
                   '<w:lang w:val="en-US"/></w:rPr>'
                   "<w:t>t</w:t></w:r></w:p>")


def test_a_run_ALREADY_in_the_house_face_does_not_stop_the_sweep():
    """The `continue` under "nothing changed". A paragraph is rarely
    uniform — a caption whose number was styled by hand, a run pasted
    from another document — so a second pass meets runs that already
    carry the face, and `break` there leaves everything BEFORE them
    untouched. The walk is back to front, so "before" is most of the
    paragraph."""
    from docxkit.edit import set_run_properties

    face = ('<w:rPr><w:rFonts w:ascii="Arial Narrow"/>'
            '<w:sz w:val="20"/></w:rPr>')
    para_xml = ("<w:p><w:r><w:t>plain</w:t></w:r>"
                f"<w:r>{face}<w:t>already</w:t></w:r></w:p>")

    out, written = set_run_properties(para_xml, HOUSE)

    assert written == 1, "the plain run, and only it"
    assert out.count('w:ascii="Arial Narrow"') == 2


def test_a_missing_anchor_is_quoted_to_SIXTY_characters():
    """Both spellings of the refusal quote the anchor, and the width is
    what makes the message a line rather than a paragraph — a caller
    passes a sentence, and this is the message they read when it does
    not match. Cut shorter and two anchors that share an opening clause
    produce the same complaint."""
    import re

    from docxkit.edit import replace_in_para
    from docxkit.errors import AnchorError

    long_anchor = ("a phrase that is nowhere in this paragraph and runs on "
                   "well past sixty characters")
    assert len(long_anchor) > 61

    with pytest.raises(AnchorError) as exc:
        replace_in_para("<w:p><w:r><w:t>short prose</w:t></w:r></w:p>",
                        long_anchor, "x")

    quoted = re.search(r"'([^']*)'", str(exc.value))
    assert quoted is not None, str(exc.value)
    assert quoted.group(1) == long_anchor[:60]


# --- the argued half of edit's list, 2026-08-20 ------------------------
#
# `_locate`'s `scope[0]` and `hits[0]` read as `[-1]`: the lines above
# each raise unless there is exactly one, which is what "ambiguity is an
# error, never a silent first-match" means in the docstring.
#
# `styled(i)`'s `0 <= i` as `-1 <= i` and as `0 is not i`. The leftward
# walk that could have passed -1 was removed by an earlier round —
# nothing read its answer — so the only caller is `styled(hi_i + 1)`
# with `hi_i >= idx >= 0`.
#
# `not allow_notes and len(touched) > 1` as `> 2`. A marker strictly
# inside the match is a zero-width run BETWEEN two text runs, so the
# runs touched are at least three: the one holding the start, the
# marker, and the one holding the end. Two touched runs and a marker
# among them cannot happen — `overlaps` is strict, so a marker that
# merely abuts the match is not touched at all, which the test for that
# says from the other side.
#
# The three `zip(..., strict=True)` as `strict=False`: every pair is
# built from one walk over the same runs.


# --- link removal, asserted as the paragraph it leaves (2026-09-17) ------
#
# A whole sweep of `edit.py` left `remove_link`, `remove_links` and
# `_drop_bookmark` with 142 survivors between them, most of them `+` on a
# string turned into `%` or `-` — mutants that raise the moment the line
# runs. Nothing in this harness ran it: the tests of link removal live in
# `test_remove_link.py`, which measures no module. These are the same
# operations asked for by VALUE, so that a removal which takes one
# bookmark too many, or leaves one behind, fails here.

_SEN = ('<w:hyperlink w:anchor="Sen1985"><w:r><w:rPr>'
        '<w:rStyle w:val="Hyperlink"/></w:rPr>'
        "<w:t>Sen (1985)</w:t></w:r></w:hyperlink>")
_TWIN = ('<w:bookmarkStart w:id="9" w:name="Sen1985txt"/>',
         '<w:bookmarkEnd w:id="9"/>')
_OTHER = ('<w:bookmarkStart w:id="3" w:name="Other"/>',
          '<w:bookmarkEnd w:id="3"/>')


def test_remove_link_takes_the_link_and_its_twin_and_NOTHING_else():
    """Another bookmark opens the paragraph, BEFORE the twin, because
    that is where `_drop_bookmark`'s walk decides things: it has to step
    over a Start that is not the twin (`continue`, not `break`), and over
    the End of that other bookmark (the `or` in its test, not `and` — with
    `and` the first Start it meets is taken whatever its name).

    The paragraph is asserted whole: the twin's END must go with its
    Start, the other pair must stay, and the label's run must come back
    as a plain run, its link style and the empty `w:rPr` shell gone."""
    p = para(_OTHER[0], run("See "), _OTHER[1],
             _TWIN[0], _SEN, _TWIN[1], run("."))

    out, label = remove_link(p, "Sen1985")

    assert label == "Sen (1985)"
    assert out == para(_OTHER[0], run("See "), _OTHER[1],
                       run("Sen (1985)"), run("."))

    kept, _ = remove_link(p, "Sen1985", drop_twin=False)
    assert kept == para(_OTHER[0], run("See "), _OTHER[1],
                        _TWIN[0], run("Sen (1985)"), _TWIN[1], run("."))


def test_remove_link_and_relabel_link_say_what_the_paragraph_DOES_link_to():
    """Both refusals build their message from the links that ARE there,
    and the two halves of that sentence are chosen by whether there are
    any. A caller reading "it has no links" beside a paragraph full of
    them goes looking in the wrong place."""
    linked = para(run("See "), _SEN, run("."))
    plain = para(run("Plain prose."))

    for undo in (remove_link, lambda p, a: relabel_link(p, a, "x")):
        with pytest.raises(AnchorError, match=(
                r"no link to 'Rowe1987' — it links to \['Sen1985'\]$")):
            undo(linked, "Rowe1987")
        with pytest.raises(AnchorError,
                           match=r"no link to 'Sen1985' — it has no links$"):
            undo(plain, "Sen1985")


def test_remove_link_counts_the_links_to_ITS_anchor_in_both_forms():
    """One link to the anchor among others: removed. Two: refused, and
    the count is exactly two, which is the smallest number `> 1` and a
    wrong `> 2` disagree on.

    The fixture's other links are the ones a sloppy anchor test would
    count: an element and a field whose anchors sort AFTER the target
    ("Zed…" > "Sen…"), so an ordering comparison in place of `==` sees
    three links. And a PAGE field — a field with a result and no
    HYPERLINK — comes FIRST, because the field walk must step over it
    (`continue`, not `break`) before it reaches the link."""
    zed_element = ('<w:hyperlink w:anchor="Zed1990"><w:r>'
                   "<w:t>Zed (1990)</w:t></w:r></w:hyperlink>")
    p = para(field("PAGE", "4"), run(" See "),
             field('HYPERLINK \\l "Sen1985"', "Sen (1985)"), run(", "),
             zed_element, run(", "),
             field('HYPERLINK \\l "Zed2000"', "Zed (2000)"), run("."))

    out, label = remove_link(p, "Sen1985")

    assert label == "Sen (1985)"
    assert visible_text(out) == visible_text(p)
    assert sorted(a for a, _ in internal_links(out)) == ["Zed1990", "Zed2000"]

    twice = para(run("See "), _SEN, run(" and "), _SEN, run("."))
    with pytest.raises(AnchorError, match="links to 'Sen1985' 2 times"):
        remove_link(twice, "Sen1985")


@pytest.mark.parametrize("lead", ["See ", "As in "])
def test_links_to_hands_back_the_label_and_the_whole_link_BY_VALUE(lead):
    """`_Link.label` and `_Link.outer` are offsets, and `_cite_audit` and
    `_cite_repair` slice the paragraph with them directly — so what they
    cover is the contract, not merely the words they contain.

    The element's label is its content and its outer span is the element.
    The field's label is everything between its `separate` and `end`
    markers, and its outer span is run-aligned: all four runs of the
    field, no shell left on either side.

    Two leads, two characters apart, because `end + 6` and `end ^ 6`
    (or `| 6`) are the same number whenever bits 1 and 2 of `end` are
    clear — and no two offsets two apart both have them clear."""
    label_runs = "<w:r><w:t>Sen (1985)</w:t></w:r>"
    element = f'<w:hyperlink w:anchor="Sen1985">{label_runs}</w:hyperlink>'
    fld = field('HYPERLINK \\l "Rowe1987"', "Rowe (1987)")
    p = para(run(lead), element, run(" and "), fld, run("."))

    el, fl = _links_to(p)

    assert (el.anchor, el.field) == ("Sen1985", False)
    assert p[el.label[0]:el.label[1]] == label_runs
    assert p[el.outer[0]:el.outer[1]] == element

    assert (fl.anchor, fl.field) == ("Rowe1987", True)
    assert p[:fl.label[0]].endswith('<w:fldChar w:fldCharType="separate"/>')
    assert p[fl.label[1]:].startswith('<w:fldChar w:fldCharType="end"/>')
    assert visible_text(p[fl.label[0]:fl.label[1]]) == "Rowe (1987)"
    assert p[fl.outer[0]:fl.outer[1]] == fld


# --- a link whose field holds another field (BACKLOG S7) ----------------
#
# Word nests fields wherever the text it copied held one: a SEQ number
# inside a caption's link, a PAGEREF inside a TOC entry, a HYPERLINK
# inside a REF. `_links_to` paired begin-to-first-end, so the outer
# field ENDED at the inner field's end marker.


def _nested_seq_link() -> str:
    """A caption link whose label carries the SEQ field that numbers it."""
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> HYPERLINK \\l "Table5" '
            "</w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + run("Table ") + field("SEQ Table \\* ARABIC", "5")
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def test_a_link_whose_result_holds_another_field_ends_at_its_OWN_end():
    """The outer span is what `remove_link` cuts. Ended at the SEQ
    field's `end` marker, the cut left the link's own `end` fldChar
    standing in the paragraph with no `begin` — a broken field, which
    reads as ordinary prose to every text gate."""
    link = _nested_seq_link()
    p = para(run("See "), link, run("."))

    (found,) = _links_to(p, "Table5")

    assert p[found.outer[0]:found.outer[1]] == link
    assert visible_text(p[found.label[0]:found.label[1]]) == "Table 5"


def test_removing_that_link_leaves_no_field_marker_UNPAIRED():
    """The damage the span above decides. Whatever `_plain_runs` keeps of
    the nested SEQ field, the paragraph must be left with as many `begin`
    markers as `end` markers — an `end` on its own is a field Word cannot
    read, and the words in front of it look untouched."""
    p = para(run("See "), _nested_seq_link(), run("."))

    out, label = remove_link(p, "Table5")

    assert label == "Table 5"
    assert visible_text(out) == "See Table 5."
    assert out.count('w:fldCharType="begin"') == \
        out.count('w:fldCharType="end"')
    assert "HYPERLINK" not in out, "the link's own instruction is gone"


def test_a_link_INSIDE_another_field_is_reported_as_itself():
    """A `REF … \\h` whose text held a link of its own: Word copies the
    link into the result. Paired begin-to-first-end, the outer REF was
    read as the HYPERLINK — one link, spanning from the REF's `begin` —
    so unwrapping it took the cross-reference field with it."""
    inner = field('HYPERLINK \\l "Sen1985"', "Sen (1985)")
    p = para(run("See "),
             '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> REF _Ref1 \\h '
             "</w:instrText></w:r>"
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             + inner + '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
             run("."))

    (found,) = _links_to(p)

    assert found.anchor == "Sen1985"
    assert p[found.outer[0]:found.outer[1]] == inner, "the inner field only"


def _sweep_para() -> str:
    """Two links to unwrap, one of each form, and a kept one LAST — the
    sweep walks back to front, so the kept link is the first it meets."""
    return para(run("See "), _SEN, run(", "),
                field('HYPERLINK \\l "Fig2"', "Figure 2"), run(" and "),
                '<w:hyperlink w:anchor="Keep"><w:r><w:t>Table 2</w:t></w:r>'
                "</w:hyperlink>", run("."))


# The sweep's own order, splice and report — `test_remove_link.py`
# already pins all of them (it is in this module's harness since
# 2026-09-18), so the test written here for them is not repeated.


def test_remove_links_keeps_a_FIELD_link_by_its_anchor_name():
    """`keep` holds bookmark NAMES, so a field link is kept by the name
    inside its instruction — not by the instruction text around it."""
    out, gone = remove_links(_sweep_para(), keep={"Fig2"})

    assert gone == ["Sen1985", "Keep"]
    assert 'HYPERLINK \\l "Fig2"' in out


# --- matching, past the edges the fixtures sat inside (2026-09-17) -------


@pytest.mark.parametrize("normalize", [False, True])
def test_rep_counts_MORE_than_256_occurrences(normalize):
    """`len(spans) != n` and `count != n`, against `is not`. CPython keeps
    one object per integer up to 256, so every count a fixture had used
    compared by identity as well as by value. A build script replacing a
    token across a whole document passes counts in the hundreds."""
    xml = "<w:t>" + "ab;" * 300 + "</w:t>"

    out = rep(xml, "ab", "cd", n=300, normalize=normalize)

    assert out == "<w:t>" + "cd;" * 300 + "</w:t>"


def test_find_normalized_reports_OVERLAPPING_occurrences():
    """The search resumes one character after the last hit, so a needle
    that overlaps itself is found at every place it starts — which is
    what makes "occurs twice" a refusal rather than a guess."""
    assert find_normalized("’’’", "''") == [(0, 2), (1, 3)]


def test_a_style_anchor_that_OVERLAPS_itself_is_refused_as_twice():
    """`_hits`, the unnormalised half, resumes one character on as well.
    Two apart, "aaa" holds "aa" once, and `italicize` would style the
    first pair of a run the caller never pinned down."""
    with pytest.raises(AnchorError, match="occurs twice"):
        italicize(para(run("aaa")), "aa")


@pytest.mark.parametrize("style", [italicize, subscript])
def test_styles_do_NOT_fold_typography_unless_asked(style):
    """`normalize: bool = False` on both public doors. Folding glyphs
    silently is how an anchor matches a phrase the caller did not type."""
    p = para(run("the authors’ note"))

    with pytest.raises(AnchorError):
        style(p, "authors' note")

    assert visible_text(style(p, "authors' note", normalize=True)) == \
        "the authors’ note"


def test_styling_a_whole_LONG_run_leaves_its_tab_where_it_was():
    """`hi == len(body)`, against `is`. Past 256 characters the two
    lengths are different objects, and the identity test sends a
    whole-run span down the SPLITTING path — which rebuilds the run
    through `set_run_text`, putting all its text into the first `w:t`
    and so moving the tab from between the two texts to after both.
    The words read the same and the page does not."""
    head, tail = "x" * 200, "y" * 100
    p = para(f"<w:r><w:t>{head}</w:t><w:tab/><w:t>{tail}</w:t></w:r>")

    out = italicize(p, head + tail)

    assert out == para(f"<w:r><w:rPr><w:i/></w:rPr><w:t>{head}</w:t>"
                       f"<w:tab/><w:t>{tail}</w:t></w:r>")
