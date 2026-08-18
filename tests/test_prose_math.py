"""The house rule: a symbol or expression belongs in OMML, not in prose.

Precision here comes from the document itself — the symbols inside its
own equations are the paper's symbols, so those characters loose in a
sentence are unformatted math. A paper that never writes theta never
gets a theta finding, which is what makes the audit worth running twice.
"""
from __future__ import annotations

import pytest
from conftest import NS

from docxkit.equations import ProseMath, document_symbols, prose_math


def doc(*paras: str) -> str:
    return (f"<w:document {NS}><w:body>" + "".join(paras)
            + "</w:body></w:document>")


def p(*bits: str) -> str:
    return "<w:p>" + "".join(bits) + "</w:p>"


def t(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def math(text: str) -> str:
    return (f'<m:oMath><m:r><m:t>{text}</m:t></m:r></m:oMath>')


def kinds(findings: list[ProseMath]) -> list[str]:
    return [f.kind for f in findings]


# ------------------------------------------------ the paper's vocabulary --


def test_the_document_supplies_its_own_symbol_vocabulary():
    xml = doc(p(math("θ"), t(" is the style parameter.")))
    assert document_symbols(xml) == {"θ"}


def test_a_symbol_the_paper_never_typesets_is_not_flagged():
    """No fixed vocabulary: a paper with no math gets no findings, and
    a Greek letter in a quoted title is not a modelling symbol."""
    xml = doc(p(t("The β-convergence literature, per Barro (1991).")))
    assert prose_math(xml) == []


def test_the_same_symbol_is_flagged_once_the_paper_typesets_it():
    xml = doc(p(math("β"), t(" is the slope.")),
              p(t("We estimate β by OLS.")))
    found = prose_math(xml)
    assert [f.symbol for f in found] == ["β"]
    assert found[0].para == 2


# ----------------------------------------------------- split expressions --


def test_an_expression_cut_by_the_run_boundary_is_the_first_finding():
    """The commonest form: the SYMBOL is math, the relation beside it is
    prose, so the two halves render in different faces."""
    xml = doc(p(t("at "), math("θi"), t("=0 and "), math("θi"), t("=1.")))
    found = [f for f in prose_math(xml) if f.kind == "split expression"]
    assert [f.symbol for f in found] == ["θi=0", "θi=1."]


def test_a_spaced_relation_is_the_same_finding():
    xml = doc(p(t("where "), math("θi"), t(" = 0 corresponds to")))
    found = [f for f in prose_math(xml) if f.kind == "split expression"]
    assert found and found[0].symbol == "θi = 0"


def test_the_whole_operand_is_reported_not_its_first_character():
    """A finding reading "cmax = 1" when the text says "cmax = 100"
    sends the reader hunting for something that is not there."""
    xml = doc(p(t("the terminal cohort "), math("cmax"), t(" = 100.")))
    found = [f for f in prose_math(xml) if f.kind == "split expression"]
    assert found and found[0].symbol == "cmax = 100."


def test_a_relation_before_the_math_is_also_caught():
    xml = doc(p(t("we impose 0 = "), math("θi"), t(" throughout")))
    assert "split expression" in kinds(prose_math(xml))


# ------------------------------------------------------- typed scripts ----


@pytest.mark.parametrize("text", ["U₁ and U₂ are shorthand",
                                  "the derivative ∂vᵢ/∂θᵢ here",
                                  "age² enters the model"])
def test_math_typed_with_unicode_scripts_is_flagged(text):
    xml = doc(p(t(text)))
    assert "typed script" in kinds(prose_math(xml))


def test_a_typed_script_is_flagged_with_no_equations_in_the_document():
    """Unlike a symbol, a subscript character needs no vocabulary: it is
    math typed as text wherever it appears."""
    xml = doc(p(t("Let x₁ denote the first period.")))
    assert document_symbols(xml) == set()
    assert kinds(prose_math(xml)) == ["typed script"]


# ---------------------------------------------------------- intervals ----


def test_interval_notation_beside_an_equation_is_flagged():
    xml = doc(p(math("θi"), t(" is an index on [0,1] of style.")))
    assert "interval" in kinds(prose_math(xml))


def test_interval_notation_in_a_results_table_is_not():
    """A paragraph doing no maths is reporting numbers; a confidence
    interval there is data, and flagging it would bury the real ones."""
    xml = doc(p(t("Effect -0.25 [-3.30, 0.56] across specifications.")))
    assert prose_math(xml) == []


# ----------------------------------------- what the rule must NOT flag ---


@pytest.mark.parametrize("text", [
    "significant for alcohol among men (p = 0.012)",
    "higher spatial inequality (mean Gini = 64.6) than Kyrgyzstan",
    "coded 0 = coercive, 1 = non-violent",
    "the sample covers 2010 = the first wave",
])
def test_statistics_prose_is_not_math(text):
    """A bare `=` between words and a number is statistics prose. A rule
    that flags "p = 0.012" is a rule nobody runs a second time, and the
    real findings drown."""
    xml = doc(p(math("θ"), t(" defined.")), p(t(text)))
    assert [f for f in prose_math(xml) if f.para == 2] == []


def test_an_n_ary_operator_the_paper_typesets_is_part_of_its_vocabulary():
    """The vocabulary is `(_SYMBOLS | _NARY) - _INVISIBLE`, and four
    mutants lived on that union: read as `&` it is very nearly empty and
    the audit finds nothing anywhere. Nothing had asked for an N-ary
    symbol, so only the `_SYMBOLS` half was ever exercised."""
    xml = doc(p(math("∑"), t(" runs over households.")),
              p(t("We then take ∑ over the panel.")))
    assert "∑" in document_symbols(xml)
    assert [f.symbol for f in prose_math(xml) if f.para == 2] == ["∑"]
    # `^` in place of `|` is NOT killable here and does not need to be:
    # the two tables are disjoint, so union and symmetric difference are
    # the same set. Asserting that is worth more than a test that pinned
    # the operator by accident.
    from docxkit.equations import _NARY, _SYMBOLS
    assert not (frozenset(_SYMBOLS) & frozenset(_NARY)), (
        "the tables now overlap — the union in _MATH_GLYPHS stopped "
        "being interchangeable with a symmetric difference")


def test_a_space_inside_an_equation_is_not_a_symbol():
    """`to_latex` has to know the non-breaking space and the invisible
    operators — they are characters it meets inside `m:t` and must
    render. Harvesting them into the paper's VOCABULARY is another
    matter: `\\text{ if }` and `~` put an NBSP in the math, and every
    non-breaking space in the reference list then read as unformatted
    math. One real finding became nineteen."""
    xml = doc(p(math("θ = f⁡(x)"), t(" is the rule.")))
    assert document_symbols(xml) == {"θ"}


def test_a_non_breaking_space_in_prose_is_not_a_finding():
    """The shape it took in the manuscript: a reference list, where the
    NBSP between initials is house style."""
    xml = doc(p(math("θ "), t(" defined.")),
              p(t("Becker, G. S. and N. Tomes. 1986.")))
    assert [f for f in prose_math(xml) if f.para == 2] == []


def test_prose_that_merely_mentions_a_greek_word_is_not_flagged():
    xml = doc(p(math("α"), t(" is the weight.")),
              p(t("Cronbach alpha exceeded 0.8 in every wave.")))
    assert [f for f in prose_math(xml) if f.para == 2] == []


# ------------------------------------------------------------ reporting --


def test_a_finding_says_where_and_what():
    xml = doc(p(math("λ"), t(" is bounded.")),
              p(t("We assume λ lies in the unit interval.")))
    found = prose_math(xml)
    assert len(found) == 1
    line = str(found[0])
    assert "λ" in line and "¶2" in line
    assert "unit interval" in line       # enough context to find it


def test_findings_come_back_in_document_order():
    xml = doc(p(math("θ"), t(" defined.")),
              p(t("First θ appears here.")),
              p(t("Later x₁ appears here.")))
    assert [f.para for f in prose_math(xml)] == [2, 3]


# --- what the first mutation run found (2026-08-18, equations 24.9 %) ---
#
# 36 survivors in this function, and all but a handful were the CONTEXT
# each finding carries — 36 characters either side of the symbol. The
# findings' kinds and symbols were asserted; the words a reader has to
# find them by were not, and this report is read against a manuscript
# where the same symbol appears fifty times.

LEFT = "a sentence of exactly thirty-six chars"
RIGHT = "and then thirty-six more after that!!"


def test_a_SYMBOL_finding_quotes_thirty_six_characters_either_side():
    xml = doc(p(math("θ"), t(" is the parameter.")),
              p(t(f"{LEFT} θ {RIGHT} and more that is cut off.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "symbol"]

    # 36 back from the symbol, 36 forward from it, and the ends are cut
    assert found.context == ("entence of exactly thirty-six chars θ "
                             "and then thirty-six more after tha")


def test_a_TYPED_SCRIPT_finding_carries_the_same_window():
    xml = doc(p(t(f"{LEFT} x₂ {RIGHT} and more that is cut off.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "typed script"]

    assert found.symbol == "₂"
    assert found.context == ("ntence of exactly thirty-six chars x₂ "
                             "and then thirty-six more after tha")


def test_a_finding_at_the_START_of_a_paragraph_is_not_cut_backwards():
    """`max(0, at - 36)` — a negative start counts from the END in
    Python, so the context would come from the last words of the
    paragraph and read as if the symbol were there."""
    xml = doc(p(math("θ"), t(" is the parameter.")),
              p(t("θ opens this paragraph and the rest follows on.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "symbol"]

    assert found.context.startswith("θ opens this paragraph")


def test_a_SPLIT_expression_quotes_the_prose_on_BOTH_sides():
    xml = doc(p(t(f"{LEFT} "), math("θi"), t(f"=0 {RIGHT} and more.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "split expression"]

    assert found.symbol == "θi=0"
    assert found.context == ("entence of exactly thirty-six chars θi=0 "
                             "and then thirty-six more after th")


def test_a_split_expression_pairs_an_equation_with_the_piece_AFTER_it():
    """`pieces[k + 1]` — the prose that follows THIS equation. Off by
    one, a symbol is reported with the words after the NEXT one, and the
    reader is sent to the wrong sentence."""
    xml = doc(p(t("first "), math("α"), t("=1 middle "), math("β"),
                t("=2 last.")))

    found = [f for f in prose_math(xml) if f.kind == "split expression"]

    assert [f.symbol for f in found] == ["α=1", "β=2"]
    assert "first α=1 middle" in found[0].context
    assert "middle β=2 last." in found[1].context


# --- the second prose_math round, from the re-measurement ---------------
#
# equations.py 24.9 % -> 10.6 % after the round above, and `prose_math`
# is still the largest cluster with 15. What is left is the pairing
# between an equation and the prose pieces around it — asserted for two
# equations, where `k + 1` and `k - 1` can still coincide — and the
# INTERVAL branch, which needs a paragraph that both typesets maths and
# writes an interval in prose, and which no fixture here had built.


def test_THREE_equations_each_pair_with_their_own_piece_of_prose():
    """`pieces[k + 1]` against `k - 1`, `k + 2` and the rest: with two
    equations a wrong index can still land on a piece that yields the
    same finding, and with three every one of them is distinguishable.
    Each equation carries its own trailing operand and its own words."""
    xml = doc(p(t("first "), math("α"), t("=1 middle "), math("β"),
                t("=2 then "), math("γ"), t("=3 last.")))

    found = [f for f in prose_math(xml) if f.kind == "split expression"]

    assert [f.symbol for f in found] == ["α=1", "β=2", "γ=3"]
    assert "first α=1 middle" in found[0].context
    assert "middle β=2 then" in found[1].context
    assert "then γ=3 last." in found[2].context


def test_an_INTERVAL_in_a_paragraph_that_TYPESETS_maths_is_a_finding():
    """A confidence interval in a results table is prose and stays
    prose; the same brackets in a paragraph that sets equations are a
    formula somebody typed. The window is the same 36 characters either
    side, and it is what tells a reader which interval was meant."""
    # Both ends of the window fall INSIDE a word on purpose: with a
    # space there, 35 and 37 characters strip back to the same string.
    # And the lead varies, because `m.end() | 36` agrees with `+ 36`
    # whenever the offset's low bits happen to be clear.
    sentence = ("The estimated parameter is bounded, unambiguously, "
                "within [0, 1] throughout every specification reported "
                "hereafter, without exception.")
    for lead in ("", "In brief: ", "As reported in the appendix table, "):
        prose = f" {lead}{sentence}"
        xml = doc(p(math("θ"), t(prose)))

        (found,) = [f for f in prose_math(xml) if f.kind == "interval"]

        at = prose.index("[0, 1]")
        assert found.symbol == "[0, 1]"
        assert found.context == prose[at - 36:at + len("[0, 1]") + 36].strip()


def test_an_interval_in_a_paragraph_with_NO_maths_is_left_alone():
    """The other half of the same rule, and the reason it exists: a
    results paragraph full of confidence intervals is not a paper
    typing formulas into prose."""
    xml = doc(p(t("The estimate is 0.42 with a 95% CI of [0.19, 0.47].")))

    assert [f for f in prose_math(xml) if f.kind == "interval"] == []


# --- the same window, on the branches that had no fixture (2026-08-19) --
#
# `piece[max(0, at - 36):at + 36]` is written twice — once for a typed
# script and once for a symbol — and `(before[-36:] + sym + after[:36])`
# is written twice too, once for an expression the equation TRAILS and
# once for one it LEADS. Each pair reads identically and each half needs
# its own fixture: the start-of-paragraph case was written for the
# symbol arm and the interval arm never had one at all.


def test_a_TYPED_SCRIPT_at_the_start_of_a_paragraph_is_not_cut_backwards():
    """`max(0, at - 36)` on the typed-script arm. A negative start
    counts from the END in Python, so the context would come from the
    last words of the paragraph and read as if the subscript were
    there — and a floor of 1 drops the character being reported."""
    xml = doc(p(t("x₂ opens this paragraph and the rest follows on.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "typed script"]

    assert found.symbol == "₂"
    assert found.context == "x₂ opens this paragraph and the rest"


def test_an_INTERVAL_at_the_start_of_a_piece_is_not_cut_backwards():
    """The same floor on the interval arm, which had no fixture near an
    edge: every lead the test above uses is longer than the window, so
    `max(0, ...)` never had to do anything."""
    # the interval opens the piece BEFORE the equation, so its offset is
    # 0 rather than 1: after `.strip()` a window starting at 1 is
    # indistinguishable from one starting at 0 whenever the character
    # there is a space, which it is on every piece that follows maths
    xml = doc(p(t("[0, 1] bounds it, as "), math("θ"), t(" shows.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "interval"]

    assert found.symbol == "[0, 1]"
    assert found.context == "[0, 1] bounds it, as"


def test_an_expression_the_equation_LEADS_carries_the_same_window():
    """`after[:36]` on the second arm — the one where the operand sits
    BEFORE the maths ("θ = " typed as prose, then the equation). Its
    fixture stopped a few characters after the equation, so the forward
    window was never full."""
    xml = doc(p(t(f"{LEFT} R² = "), math("θ"), t(f" {RIGHT} and more.")))

    (found,) = [f for f in prose_math(xml) if f.kind == "split expression"]

    assert found.symbol == "R² =θ"
    assert found.context == ("ce of exactly thirty-six chars R² = θ and "
                             "then thirty-six more after that")
