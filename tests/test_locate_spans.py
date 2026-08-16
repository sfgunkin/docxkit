"""`_locate`'s run spans, stated as values.

`_locate` computes what every other function in `edit.py` consumes: the
paragraph's runs, each run's span in VISIBLE text, and the one span of
the anchor. Ten mutants survived in it on 2026-08-16 with 95 % line
coverage, because every caller asserted on the TEXT that came out and
none on the offsets that got it there.

The offsets are the part with an incident behind them. They index
``visible_text``, which counts everything a reader sees — including the
maths, which lives in an ``m:r`` inside an ``m:oMath`` SIBLING of the
runs, not in a ``w:r``. Joining the runs alone gave a shorter string,
and on a DSI §6.3 paragraph carrying five inline symbols the citation
link wrapped «ему (Friedman» instead of «(Friedman 1992)», four
characters early.
"""
from __future__ import annotations

import pytest
from conftest import para, run

from docxkit._xml import visible_text
from docxkit.edit import _locate
from docxkit.errors import AnchorError

MATH = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
        'officeDocument/2006/math"><m:r><m:t>{}</m:t></m:r></m:oMath>')


def _spans_of(para_xml: str, anchor: str, **kw):
    _runs, spans, at, end = _locate(para_xml, anchor, **kw)
    return spans, at, end


def test_the_spans_tile_the_visible_text_of_a_simple_paragraph():
    p = para(run("The share "), run("rose to "), run("0.15."))
    spans, at, end = _spans_of(p, "rose")

    assert spans == [(0, 10), (10, 18), (18, 23)]
    assert visible_text(p)[at:end] == "rose"
    assert (at, end) == (10, 14)


def test_a_span_COUNTS_the_maths_between_runs():
    """The DSI §6.3 incident. An equation sits between two runs and a
    reader sees it, so every offset after it is shifted by its width —
    joining the runs alone put the citation link four characters early."""
    p = ("<w:p>" + run("where ") + MATH.format("τ") + run(" is time")
         + "</w:p>")
    spans, at, end = _spans_of(p, "is time")

    assert visible_text(p) == "where τ is time"
    assert spans == [(0, 6), (7, 15)], (
        "the second run must start AFTER the equation's one character")
    assert visible_text(p)[at:end] == "is time"


def test_a_two_character_symbol_shifts_the_spans_by_two():
    p = ("<w:p>" + run("where ") + MATH.format("xy") + run(" is time")
         + "</w:p>")
    spans, _, _ = _spans_of(p, "is time")
    assert spans == [(0, 6), (8, 16)]


def test_the_span_of_a_run_with_no_text_is_EMPTY_and_in_place():
    """A note marker shows nothing, so it takes no width — but it still
    holds its position in the sequence."""
    marker = '<w:r><w:footnoteReference w:id="3"/></w:r>'
    p = "<w:p>" + run("before") + marker + run("after") + "</w:p>"
    spans, _, _ = _spans_of(p, "after")
    assert spans == [(0, 6), (6, 6), (6, 11)]


def test_within_scopes_the_anchor_to_ONE_occurrence():
    """A target that is not unique in the paragraph — a single letter, a
    repeated word — is still addressable through a longer anchor."""
    p = para(run("the rate of 3 and the rate of 5"))
    _, at, end = _spans_of(p, "3", within="rate of 3")
    assert visible_text(p)[at:end] == "3"
    assert at == 12

    _, at2, end2 = _spans_of(p, "5", within="rate of 5")
    assert (at2, end2) == (30, 31)


def test_within_returns_offsets_into_the_WHOLE_paragraph():
    """Not into the scoped slice: every caller splices back into the
    paragraph, so a `within`-relative offset would land early by exactly
    the length of the text before the scope."""
    p = para(run("alpha beta "), run("gamma beta delta"))
    _, at, end = _spans_of(p, "beta", within="gamma beta")
    assert (at, end) == (17, 21)
    assert visible_text(p)[at:end] == "beta"


def test_an_ambiguous_anchor_is_an_ERROR_never_a_first_match():
    p = para(run("the gap and the gap"))
    with pytest.raises(AnchorError, match="occurs twice"):
        _locate(p, "the gap")


def test_an_ambiguous_WITHIN_is_an_error_too():
    p = para(run("rate of 3 and rate of 3"))
    with pytest.raises(AnchorError, match="occurs twice"):
        _locate(p, "3", within="rate of 3")


def test_a_missing_anchor_names_what_was_looked_for():
    p = para(run("nothing here"))
    with pytest.raises(AnchorError, match="not in paragraph"):
        _locate(p, "elsewhere")
    with pytest.raises(AnchorError, match=r"within="):
        _locate(p, "here", within="no such scope")


def test_normalize_matches_through_words_glyph_substitutions():
    """A manuscript mixes straight and curly apostrophes because
    autocorrect ran on some paragraphs and not others."""
    p = para(run("maintain workers’ productivity"))
    _, at, end = _spans_of(p, "workers' productivity", normalize=True)
    assert visible_text(p)[at:end] == "workers’ productivity"
    with pytest.raises(AnchorError):
        _locate(p, "workers' productivity")


def test_the_runs_returned_are_the_paragraphs_own_matches():
    """Callers splice with `run.start()`/`run.end()`, so the matches must
    index the paragraph they were given."""
    p = para(run("alpha "), run("beta"))
    runs, spans, _at, _end = _locate(p, "beta")
    assert [p[r.start():r.end()] for r in runs] == [m.group(0) for m in runs]
    assert p[runs[1].start():runs[1].end()].endswith("</w:r>")
    assert len(runs) == len(spans)
