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
