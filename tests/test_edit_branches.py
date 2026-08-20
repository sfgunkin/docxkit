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

from docxkit._xml import RUN_RE, visible_text
from docxkit.edit import italicize, preserve_space, replace_in_para, subscript
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
