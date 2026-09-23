"""`wrap_visible_span` at offsets that are not zero.

The positional core of every linking pass: it takes offsets into a
paragraph's VISIBLE text and rewrites the runs under them. Its
arithmetic is `at - fs` and `end - ls` — the span's offset minus the
offset the run it lands in starts at — and when a fixture's span starts
in the FIRST run, `fs` is 0 and `at - 0`, `at + 0` and `at << 0` are one
number. 23 of `_cite_grammar.py`'s 65 real survivors (2026-08-19) were
in this one function, almost all of them on those two subtractions and
on the two run-boundary comparisons beside them.

So every span here starts in a later run, and the run boundaries are
placed ON the span's edges deliberately: `sp[1] > at` and `sp[0] < end`
decide which runs are covered, and a run that ENDS exactly where the
span begins is the case that tells `>` from `>=`. Word splits runs at
every formatting change and every spell-check pass, so a citation
sitting across a boundary is the ordinary case, not a constructed one.
"""
from __future__ import annotations

import re

import pytest

from docxkit._xml import RUN_RE, printed_text, run_holds_content, visible_text
from docxkit.citations import wrap_visible_span
from docxkit.errors import AnchorError


def _p(*bodies: str) -> str:
    """A paragraph of one run per argument."""
    return ("<w:p>" + "".join(
        f'<w:r><w:t xml:space="preserve">{b}</w:t></w:r>' for b in bodies)
        + "</w:p>")


def _linked(out: str) -> str:
    """The visible text the hyperlink wraps."""
    m = re.search(r"<w:hyperlink[^>]*>(.*?)</w:hyperlink>", out, re.DOTALL)
    assert m is not None, out
    return visible_text(m.group(1))


def _wrap(para: str, phrase: str, anchor: str = "A") -> str:
    at = visible_text(para).index(phrase)
    out = wrap_visible_span(para, at, at + len(phrase), anchor)
    assert visible_text(out) == visible_text(para), "no glyph may move"
    return out


def test_a_span_starting_INSIDE_a_later_run_keeps_the_head_of_that_run():
    """`fbody[:at - fs]`: the part of the run before the span stays
    outside the link. Measured from the run's own start — the whole
    point of `- fs` — and with the run starting at 9 rather than 0 the
    three arithmetic spellings of that line give three different cuts.
    """
    para = _p("Earlier. ", "As Smith 2020 argued, ", "later.")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert out.index("Earlier. ") < out.index("As ") < out.index("<w:hyper")


def test_a_span_ENDING_inside_a_later_run_keeps_the_tail_of_it():
    """`lbody[end - ls:]` — the mirror, and the one that decides where
    the blue stops. A link running on to the end of the paragraph is
    what an off-by-a-run tail looks like in Word."""
    para = _p("Earlier. ", "See ", "Smith 2020 and others.")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert visible_text(out).endswith("Smith 2020 and others.")
    assert " and others." not in _linked(out)


def test_a_run_that_ENDS_exactly_where_the_span_starts_is_left_alone():
    """`sp[1] > at`, not `>=`: a run whose last character is the one
    before the span contributes nothing to the link, and including it
    puts an empty run inside the hyperlink — which Word renders as a
    blue space before the citation."""
    para = _p("Cited in ", "Smith 2020", " and elsewhere.")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert out.index("Cited in ") < out.index("<w:hyperlink")
    assert out.count("<w:r>") == 3, "no empty run before the link"


def test_a_run_that_STARTS_exactly_where_the_span_ends_is_left_alone():
    """`sp[0] < end`, not `<=`. The same edge at the other end: under
    `<=` the run after the span joins the covered list, `last` becomes
    a run the link does not reach into, and the tail slice cuts at a
    negative offset."""
    para = _p("See ", "Smith 2020", ", who argues otherwise.")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert visible_text(out).endswith(", who argues otherwise.")
    # `end < le`, not `<=`: with the span ending exactly at the covered
    # run's own end there is no tail, and the `<=` spelling writes an
    # EMPTY run after the link instead of nothing at all
    assert out.count("<w:r>") == 3


def test_a_span_that_starts_and_ends_mid_run_three_runs_apart():
    """Both slices non-trivial at once, at offsets chosen so that no
    other arithmetic agrees with subtraction: the span starts 9
    characters into its run (`at - fs` 9, `at ^ fs` 15) and ends 23
    into the last one (`end - ls` 23, `end % ls` 5). A fixture whose
    numbers are small or aligned lets `^`, `%`, `<<` and `+` all pass
    for `-`, which is what 23 survivors in one function look like."""
    para = _p("As ", "noted by Smith ", "and Jones and Wong 2021 in passing.")

    out = _wrap(para, "Smith and Jones and Wong 2021", "SJW2021")

    assert _linked(out) == "Smith and Jones and Wong 2021"
    assert visible_text(out) == ("As noted by Smith and Jones and Wong 2021 "
                                 "in passing.")
    assert out.startswith('<w:p><w:r><w:t xml:space="preserve">As </w:t>')
    assert visible_text(out[out.index("</w:hyperlink>"):]) == " in passing."


def test_a_span_across_THREE_runs_styles_the_middle_one_too():
    """`middle` is every run strictly between the first and the last,
    restyled in place. Word writes runs like this whenever an author
    italicises one word of a citation, and a middle run left unstyled
    is a citation half blue and half black."""
    para = _p("As ", "Smith ", "and ", "Jones 2021", " showed.")

    out = _wrap(para, "Smith and Jones 2021", "SJ2021")

    assert _linked(out) == "Smith and Jones 2021"
    inner = re.search(r"<w:hyperlink[^>]*>(.*?)</w:hyperlink>", out,
                      re.DOTALL)
    assert inner is not None
    assert inner.group(1).count("<w:r>") == 3, "head, middle, tail"
    assert inner.group(1).count('w:val="Hyperlink"') == 3


def test_the_span_may_start_at_the_very_first_character_of_a_run():
    """`at > fs` is False here, so there is no "before" fragment at all
    — the branch that returns "" rather than a run with empty text. An
    empty `w:r` in the paragraph is not an error Word reports; it is a
    zero-width formatting island that the next edit inherits."""
    para = _p("Earlier. ", "Smith 2020 argued this.")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert "<w:t xml:space=\"preserve\"></w:t>" not in out
    assert out.count("<w:r>") + out.count("<w:r ") == 3


def test_a_span_covering_a_whole_later_run_exactly():
    """Both edges on run boundaries at once: no head, no tail, and the
    run itself is the only covered one. `first is last` with neither
    slice taken — the shape `link_rest` produces when a citation was
    already its own run."""
    para = _p("Cited in ", "Smith 2020", " and elsewhere.")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert out.count("<w:hyperlink") == 1


def test_an_offset_past_the_last_run_is_refused_not_silently_clipped():
    """The guard is `<=` on both sides: `at == end == text_len` is an
    empty span at the very end, which is in range but covers nothing,
    and it must reach the "empty" refusal rather than index a run that
    is not there."""
    para = _p("Smith 2020 argued this.")
    n = len(visible_text(para))

    with pytest.raises(AnchorError, match="is empty"):
        wrap_visible_span(para, n, n, "A")

    with pytest.raises(AnchorError, match="not inside"):
        wrap_visible_span(para, n, n + 1, "A")


def test_the_span_is_measured_in_visible_text_including_the_maths():
    """The DSI §6.2 failure, kept as a fixture whose first run is not
    the one the span lands in: an `m:r` carries glyphs that `RUN_RE`
    cannot see, so a cursor advanced over `w:r` alone lands short by
    exactly the equation's length."""
    math = "<m:oMath><m:r><m:t>γ∈{0,25}</m:t></m:r></m:oMath>"
    para = ('<w:p><w:r><w:t xml:space="preserve">Weights </w:t></w:r>'
            + math + '<w:r><w:t xml:space="preserve"> vary, per Smith 2020'
            ".</w:t></w:r></w:p>")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"


_MATH_FIRST = ("<w:p><m:oMath><m:r><m:t>xyz</m:t></m:r></m:oMath>"
               '<w:r><w:t xml:space="preserve">Smith 2020 said</w:t></w:r>'
               "<m:oMath><m:r><m:t>abcde</m:t></m:r></m:oMath>"
               '<w:r><w:t xml:space="preserve"> so.</w:t></w:r></w:p>')


@pytest.mark.parametrize(("at", "end"), [
    (0, 7),                    # inside the leading equation
    (2, 9),
    (18, 25),                  # inside the middle one
])
def test_a_span_STARTING_inside_an_equation_is_refused_in_its_own_words(
        at, end):
    """Backlog S3, 2026-09-18: a start inside OMML reached `split_run` as
    a negative offset and came back as `ValueError: split_run: offset -3
    is before the run` — no paragraph, not the module's error."""
    with pytest.raises(AnchorError, match="starts inside an equation") as e:
        wrap_visible_span(_MATH_FIRST, at, end, "A")

    assert "xyzSmith" in str(e.value)          # the paragraph is quoted


def test_a_span_BETWEEN_two_equations_still_wraps():
    out = wrap_visible_span(_MATH_FIRST, 3, 13, "A")

    assert _linked(out) == "Smith 2020"


def test_a_span_on_a_run_edge_past_256_leaves_no_EMPTY_run():
    """`at <= fs` is what keeps the run before the span whole and puts no
    empty run in front of the link. Past offset 256 two equal offsets are
    two int objects, so an identity test there left `<w:r></w:r>` behind
    (a survivor of the 2026-09-12 replay)."""
    para = _p("x" * 300, "Smith 2020", " tail")

    out = _wrap(para, "Smith 2020")

    assert _linked(out) == "Smith 2020"
    assert "<w:r></w:r>" not in out, out[:400]


# --- the printing children at a run's edge (S1, 2026-09-17) -------------
#
# `split_run` puts a child standing exactly at the cut on the LEFT, in
# document order — which is what keeps the END of a wrap whole — so the
# half cut at a run's own start holds every printing child in front of
# that run's first `w:t`. Dropping the half on sight, as "there is no
# before fragment here" did, DELETED that child: a tab, a no-break
# hyphen, a line break, none of which `visible_text` renders. The
# paragraph read identically before and after, `_wrap`'s own "no glyph
# may move" assertion passed, and the page had lost a character.
#
# The other side of backlog S1 of 2026-08-21, where `set_run_text` COPIED
# the same children into every fragment instead.


def test_a_no_break_hyphen_OPENING_the_wrapped_run_is_not_deleted():
    """Word splits a run at a no-break hyphen, so "Smith‑Jones (2003)"
    linked from "Jones" is the ordinary shape and not a constructed one:
    the second run opens with the hyphen, and the span starts at its
    first visible character."""
    para = ('<w:p><w:r><w:t>Smith</w:t></w:r>'
            '<w:r><w:noBreakHyphen/><w:t xml:space="preserve">Jones (2003)'
            "</w:t></w:r></w:p>")

    out = _wrap(para, "Jones (2003)")

    assert printed_text(out) == printed_text(para) == "Smith‑Jones (2003)"
    assert _linked(out) == "Jones (2003)"
    assert out.index("<w:noBreakHyphen/>") < out.index("<w:hyperlink"), \
        "the hyphen belongs to the word, not to the link's label"


def test_a_TAB_opening_the_wrapped_run_is_not_deleted_either():
    """The same at the paragraph's other common edge: a citation run
    that Word opened with a tab."""
    para = ('<w:p><w:r><w:t xml:space="preserve">see </w:t></w:r>'
            "<w:r><w:tab/><w:t>Rowe 1987</w:t></w:r></w:p>")

    out = _wrap(para, "Rowe 1987")

    assert printed_text(out) == printed_text(para) == "see \tRowe 1987"
    assert _linked(out) == "Rowe 1987"


def test_a_printing_child_at_the_END_of_the_wrapped_run_survives_too():
    """The half at the other edge, which the same guard now reads: the
    right half of a cut at the run's full length is empty, and the tab
    rides left into the link. It is still on the page, in its place."""
    para = ('<w:p><w:r><w:t xml:space="preserve">see </w:t></w:r>'
            "<w:r><w:t>Rowe 1987</w:t><w:tab/></w:r>"
            "<w:r><w:t>and more</w:t></w:r></w:p>")

    out = _wrap(para, "Rowe 1987")

    assert printed_text(out) == printed_text(para) == "see Rowe 1987\tand more"
    assert _linked(out) == "Rowe 1987"


def _holds_nothing(out: str) -> list[str]:
    """Every run in `out` that holds nothing — the shells a wrap leaves.

    Asked through `run_holds_content`, the primitive the guard itself
    calls, rather than by looking for the literal `<w:r></w:r>`: the
    shell of a run whose `w:t` carried `xml:space` comes back as
    `<w:r><w:t xml:space="preserve"></w:t></w:r>`, which that string
    does not match. Ten mutants of the two guards below lived behind
    exactly that gap in the assertion.
    """
    return [m.group(0) for m in RUN_RE.finditer(out)
            if not run_holds_content(m.group(0))]


def test_no_wrap_leaves_behind_a_run_that_holds_NOTHING():
    """The property both edge guards exist for, asked of the output
    rather than of either guard: after a wrap, every run still in the
    paragraph holds something.

    Asked through `run_holds_content`, which is the primitive the guards
    themselves call — the test above looks for the literal
    `<w:r></w:r>`, and the shell of a run whose `w:t` carried
    `xml:space` is `<w:r><w:t xml:space="preserve"></w:t></w:r>`, which
    that string does not match.

    It kills no mutant of either guard, and that is the finding it
    records rather than a shortcoming: `split_run` returns `''` for the
    right half of a cut at a run's own end, for every run shape — plain,
    styled, and with a tab, a hyphen or a break after the text — so
    `after` is already empty wherever `end >= le` and the guard beneath
    it cannot change the paragraph. The left half of a cut at 0 IS a
    shell, which is why the guard above it does work. If `split_run`
    ever returns a shell on the right, this test is what notices.
    """
    para = _p("see ", "Rowe 1987", " and on")

    out = _wrap(para, "Rowe 1987")

    assert _linked(out) == "Rowe 1987"
    assert _holds_nothing(out) == [], out


def test_a_span_ending_INSIDE_the_maths_past_its_last_run():
    """`end > le`, and the asymmetry with the guard above it: offsets
    count the maths and `RUN_RE` does not, so a span running to the end
    of `Rowe 1987xy` ends two characters past the last `w:r` it covers,
    and `split_run` is asked for a cut past the run's length.

    That RETURNS, and the link stops at the prose. The mirror case —
    maths BEFORE the prose, so the span starts before its first covered
    run — is refused with the module's own AnchorError (it was a
    helper's `ValueError` until 2026-09-23; see the test above)."""
    math = "<m:oMath><m:r><m:t>xy</m:t></m:r></m:oMath>"
    para = ('<w:p><w:r><w:t xml:space="preserve">see </w:t></w:r>'
            '<w:r><w:t xml:space="preserve">Rowe 1987</w:t></w:r>'
            + math + "</w:p>")

    out = _wrap(para, "Rowe 1987xy")

    assert _holds_nothing(out) == [], out
    assert printed_text(out) == printed_text(para), "no glyph may move"


def test_a_run_with_nothing_but_its_PROPERTIES_is_still_dropped():
    """The guard may not buy the children back by keeping every half:
    the shell of a run — open tag, `w:rPr`, close — is a zero-width
    formatting island, and putting one in front of every link is what
    the drop was for."""
    para = ('<w:p><w:r><w:t xml:space="preserve">see </w:t></w:r>'
            '<w:r><w:rPr><w:i/></w:rPr><w:t>Rowe 1987</w:t></w:r></w:p>')

    out = _wrap(para, "Rowe 1987")

    assert _linked(out) == "Rowe 1987"
    assert "<w:r><w:rPr><w:i/></w:rPr></w:r>" not in out
    assert out.count("<w:r>") == 2, out
