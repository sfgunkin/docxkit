"""OMML -> LaTeX: every supported construct, plus the gap contract.

Fixtures are hand-written OMML (the shapes Word's MML2OMML.XSL emits),
so the tests run without Word or its XSL. A round-trip test through
latex_to_omml runs only where the XSL exists.
"""
from __future__ import annotations

import pytest

from docxkit.equations import to_latex
from docxkit.errors import ConversionGap


def m(body: str) -> str:
    return f"<m:oMath>{body}</m:oMath>"


def r(text: str) -> str:
    return f"<m:r><m:t>{text}</m:t></m:r>"


def test_plain_runs_and_operators():
    assert to_latex(m(r("x=y+2"))) == "x=y+2"


def test_symbol_mapping_keeps_commands_apart():
    assert to_latex(m(r("α≤β×∞"))) == r"\alpha \le \beta \times \infty"


def test_math_alphanumeric_glyphs_map_to_their_base_letter():
    # 𝑥 (MATHEMATICAL ITALIC SMALL X) and 𝛽 (ITALIC SMALL BETA)
    assert to_latex(m(r("\U0001d465=\U0001d6fd"))) == r"x=\beta"


def test_fraction():
    body = ("<m:f><m:num>" + r("a") + "</m:num>"
            "<m:den>" + r("b") + "</m:den></m:f>")
    assert to_latex(m(body)) == r"\frac{a}{b}"


def test_linear_fraction_uses_a_solidus():
    body = ('<m:f><m:fPr><m:type m:val="lin"/></m:fPr>'
            "<m:num>" + r("a") + "</m:num><m:den>" + r("b")
            + "</m:den></m:f>")
    assert to_latex(m(body)) == "{a}/{b}"


def test_sub_sup_and_both():
    sup = "<m:sSup><m:e>" + r("x") + "</m:e><m:sup>" + r("2") \
        + "</m:sup></m:sSup>"
    sub = "<m:sSub><m:e>" + r("x") + "</m:e><m:sub>" + r("i") \
        + "</m:sub></m:sSub>"
    both = ("<m:sSubSup><m:e>" + r("x") + "</m:e><m:sub>" + r("i")
            + "</m:sub><m:sup>" + r("2") + "</m:sup></m:sSubSup>")
    assert to_latex(m(sup)) == "{x}^{2}"
    assert to_latex(m(sub)) == "{x}_{i}"
    assert to_latex(m(both)) == "{x}_{i}^{2}"


def test_radical_with_and_without_degree():
    plain = ('<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr>'
             "<m:deg/><m:e>" + r("x") + "</m:e></m:rad>")
    cubed = ("<m:rad><m:deg>" + r("3") + "</m:deg><m:e>" + r("x")
             + "</m:e></m:rad>")
    assert to_latex(m(plain)) == r"\sqrt{x}"
    assert to_latex(m(cubed)) == r"\sqrt[3]{x}"


def test_nary_sum_with_limits():
    body = ('<m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr>'
            "<m:sub>" + r("i=1") + "</m:sub><m:sup>" + r("n")
            + "</m:sup><m:e>" + r("x_i") + "</m:e></m:nary>")
    assert to_latex(m(body)) == r"\sum_{i=1}^{n} {x\_i}"


def test_default_nary_is_an_integral():
    body = ("<m:nary><m:sub>" + r("0") + "</m:sub><m:sup>" + r("1")
            + "</m:sup><m:e>" + r("f") + "</m:e></m:nary>")
    assert to_latex(m(body)) == r"\int_{0}^{1} {f}"


def test_delimiters_default_and_custom():
    paren = "<m:d><m:e>" + r("x") + "</m:e></m:d>"
    brack = ('<m:d><m:dPr><m:begChr m:val="["/><m:endChr m:val="]"/>'
             "</m:dPr><m:e>" + r("x") + "</m:e></m:d>")
    assert to_latex(m(paren)) == r"\left( x \right)"
    assert to_latex(m(brack)) == r"\left[ x \right]"


def test_conditional_expectation_reads_correctly():
    body = ('<m:d><m:dPr><m:sepChr m:val="|"/></m:dPr>'
            "<m:e>" + r("y") + "</m:e><m:e>" + r("x") + "</m:e></m:d>")
    assert to_latex(m(body)) == r"\left( y \middle| x \right)"


def test_known_function_and_operatorname():
    sin = ("<m:func><m:fName>" + r("sin") + "</m:fName><m:e>" + r("x")
           + "</m:e></m:func>")
    var = ("<m:func><m:fName>" + r("Var") + "</m:fName><m:e>" + r("x")
           + "</m:e></m:func>")
    assert to_latex(m(sin)) == r"\sin {x}"
    assert to_latex(m(var)) == r"\operatorname{Var} {x}"


def test_lim_takes_its_limit_underneath():
    fname = ("<m:limLow><m:e>" + r("lim") + "</m:e><m:lim>" + r("n→∞")
             + "</m:lim></m:limLow>")
    body = ("<m:func><m:fName>" + fname + "</m:fName><m:e>" + r("x_n")
            + "</m:e></m:func>")
    assert to_latex(m(body)) == r"\lim_{n\to \infty} {x\_n}"


def test_accents_bar_and_braces():
    hat = ('<m:acc><m:accPr><m:chr m:val="̂"/></m:accPr><m:e>'
           + r("β") + "</m:e></m:acc>")
    over = ('<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>'
            + r("x") + "</m:e></m:bar>")
    brace = "<m:groupChr><m:e>" + r("abc") + "</m:e></m:groupChr>"
    assert to_latex(m(hat)) == r"\hat{\beta}"
    assert to_latex(m(over)) == r"\overline{x}"
    assert to_latex(m(brace)) == r"\underbrace{abc}"


def test_matrix_and_equation_array():
    mat = ("<m:m><m:mr><m:e>" + r("a") + "</m:e><m:e>" + r("b")
           + "</m:e></m:mr><m:mr><m:e>" + r("c") + "</m:e><m:e>"
           + r("d") + "</m:e></m:mr></m:m>")
    arr = ("<m:eqArr><m:e>" + r("x=1") + "</m:e><m:e>" + r("y=2")
           + "</m:e></m:eqArr>")
    assert to_latex(m(mat)) == \
        r"\begin{matrix} a & b \\ c & d \end{matrix}"
    assert to_latex(m(arr)) == r"\begin{aligned} x=1 \\ y=2 \end{aligned}"


def test_upright_run_becomes_text():
    body = ("<m:r><m:rPr><m:nor/></m:rPr><m:t>if</m:t></m:r>")
    assert to_latex(m(body)) == r"\text{if}"


def test_w_runs_and_bookmarks_contribute_nothing():
    body = ('<w:bookmarkStart w:id="1" w:name="eq1"/>' + r("x")
            + '<w:bookmarkEnd w:id="1"/>')
    assert to_latex(m(body)) == "x"


def test_an_unknown_element_is_marked_not_dropped():
    out = to_latex(m("<m:zzz>" + r("x") + "</m:zzz>"))
    assert "[?m:zzz]" in out
    assert "x" in out                          # content still present


def test_strict_raises_on_a_gap():
    with pytest.raises(ConversionGap, match="m:zzz"):
        to_latex(m("<m:zzz/>"), strict=True)


def test_a_document_slice_without_namespace_declarations_parses():
    # equations.equations() hands back raw slices of document.xml, which
    # carry no xmlns:m of their own
    assert to_latex(m(r("x"))) == "x"


def test_round_trip_through_words_own_xsl():
    pytest.importorskip("latex2mathml")
    from docxkit.equations import find_mml2omml_xsl, latex_to_omml
    from docxkit.errors import PackageError
    try:
        find_mml2omml_xsl()
    except PackageError:
        pytest.skip("Word's MML2OMML.XSL not installed")
    omml = latex_to_omml(r"\frac{\alpha}{2}+x^{2}")
    out = to_latex(omml)
    assert r"\frac" in out and r"\alpha" in out
    assert "^" in out and "[?" not in out
