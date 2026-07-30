"""Anchors that match through Word's typographic substitutions.

A manuscript mixes straight and curly apostrophes because autocorrect ran on
some paragraphs and not others, so an anchor written one way silently misses
the other. Reproduced on the AFI paper: "maintain workers RSQUO productivity"
raised AnchorError while the ASCII form matched, in the same document.
"""
from __future__ import annotations

import pytest
from conftest import document, para, run

from docxkit import para_slice, rep
from docxkit.edit import find_normalized, replace_in_para
from docxkit.errors import AnchorError

CURLY = "maintain workers’ productivity"
STRAIGHT = "maintain workers' productivity"


# ------------------------------------------------------- find_normalized ---

def test_find_normalized_matches_across_quote_styles():
    assert find_normalized(f"we {CURLY} here", STRAIGHT)
    assert find_normalized(f"we {STRAIGHT} here", CURLY)


def test_find_normalized_offsets_index_the_original():
    """Every GLYPH_MAP substitution is one character for one character, so
    a normalized offset is still valid in the untouched string."""
    hay = f"we {CURLY} here"
    (start, end), = find_normalized(hay, STRAIGHT)
    assert hay[start:end] == CURLY


def test_find_normalized_folds_dashes_and_minus():
    assert find_normalized("a – b", "a - b")      # en dash
    assert find_normalized("x − y", "x - y")      # minus sign


def test_find_normalized_returns_every_hit():
    assert len(find_normalized("a'b a’b", "a'b")) == 2


# ------------------------------------------------------- replace_in_para ---

def test_replace_in_para_still_refuses_the_wrong_style_by_default():
    """The default stays strict, so existing builds cannot change meaning."""
    p = para(run(f"we {CURLY} here"))
    with pytest.raises(AnchorError):
        replace_in_para(p, STRAIGHT, "X")


def test_replace_in_para_normalize_matches_and_writes_verbatim():
    p = para(run(f"we {CURLY} here"))
    out = replace_in_para(p, STRAIGHT, "REPLACED", normalize=True)
    assert "REPLACED" in out
    assert CURLY not in out


def test_replace_in_para_normalize_still_detects_duplicates():
    p = para(run(f"{CURLY} and {STRAIGHT}"))
    with pytest.raises(AnchorError, match="occurs twice"):
        replace_in_para(p, STRAIGHT, "X", normalize=True)


def test_replace_in_para_normalize_spans_fragmented_runs():
    """Word splits prose across runs; normalization must not break that."""
    p = para(run("maintain workers"), run("’ produc"), run("tivity here"))
    out = replace_in_para(p, STRAIGHT, "OK", normalize=True)
    assert "OK" in out


# ------------------------------------------------------------ para_slice ---

def test_para_slice_normalize_finds_the_autocorrected_paragraph():
    xml = document(para(run("plain")) + para(run(f"we {CURLY} here")))
    with pytest.raises(AnchorError):
        para_slice(xml, STRAIGHT)
    start, end = para_slice(xml, STRAIGHT, normalize=True)
    assert CURLY in xml[start:end]


def test_para_slice_normalize_applies_to_the_also_disambiguator():
    xml = document(para(run(f"{CURLY} (1)")) + para(run(f"{CURLY} (2)")))
    start, end = para_slice(xml, STRAIGHT, also="(2)", normalize=True)
    assert "(2)" in xml[start:end]


# ------------------------------------------------------------------ rep ---

def test_rep_normalize_matches_and_asserts_the_count():
    xml = f"<w:t>{CURLY}</w:t>"
    assert "DONE" in rep(xml, STRAIGHT, "DONE", normalize=True)
    with pytest.raises(AnchorError, match=r"found 1x \(need 2\)"):
        rep(xml, STRAIGHT, "DONE", n=2, normalize=True)


def test_rep_default_is_unchanged():
    with pytest.raises(AnchorError):
        rep(f"<w:t>{CURLY}</w:t>", STRAIGHT, "X")
