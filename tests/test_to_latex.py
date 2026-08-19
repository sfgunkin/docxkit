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


def test_a_barless_fraction_is_a_binomial_stack():
    """`noBar` is how Word writes a binomial coefficient — a stack with
    no rule. Sixteen mutants lived on the slicing that unwraps the two
    braced arguments, because nothing had ever built one: the arguments
    come back as `{a}` and `{b}`, and `\\atop` takes them bare inside a
    single group."""
    body = ('<m:f><m:fPr><m:type m:val="noBar"/></m:fPr>'
            "<m:num>" + r("n") + "</m:num><m:den>" + r("k")
            + "</m:den></m:f>")
    assert to_latex(m(body)) == r"{n \atop k}"


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


# --- what the equations mutation run of 2026-08-18 found ------------------
#
# 24.9 % real survival, and after `prose_math` the clusters were all in
# this converter: 19 in `e_sPre`, 7 in `e_groupChr`, 7 in `e_borderBox`,
# 5 in `e_phant`, 4 in `e_r`. Every one sat on a `+` between two strings
# — mutated to `&`, `|`, `^`, which would raise on the first call — so
# they were not weak assertions but shapes NOTHING here had ever built.
# Word writes all of them: prescripts in isotope and tensor notation,
# an over-arrow on a vector, `\boxed` for a highlighted result, and
# `\phantom` wherever an author aligned two lines by hand.


def test_a_PRESCRIPT_puts_sub_and_sup_BEFORE_the_base():
    """`m:sPre` is Word's prescript — isotope and tensor notation. LaTeX
    has no operator for it, so the sub and the sup hang off an empty
    group `{}` and the base follows: order the four pieces any other way
    and the carbon-14 reads as an exponent on the element."""
    body = ("<m:sPre><m:sub>" + r("2") + "</m:sub><m:sup>" + r("14")
            + "</m:sup><m:e>" + r("C") + "</m:e></m:sPre>")
    assert to_latex(m(body)) == "{}_{2}^{14}{C}"


def test_an_OVERBRACE_is_told_from_an_underbrace_by_its_character():
    """The default `groupChr` is U+23DF and the test above covers it;
    U+23DE is the same element with the brace the other way up, and only
    the character says which."""
    body = ('<m:groupChr><m:groupChrPr><m:chr m:val="⏞"/></m:groupChrPr>'
            "<m:e>" + r("abc") + "</m:e></m:groupChr>")
    assert to_latex(m(body)) == r"\overbrace{abc}"


def test_ANY_OTHER_grouping_character_sits_above_or_below_by_pos():
    r"""A vector's arrow, a tilde, an author's own glyph: not a brace, so
    it becomes `\overset` or `\underset` around the character itself —
    and `pos` is the only thing that decides which. `top` is the sole
    value that lifts it; Word writes `bot` and omits the element
    entirely, and both mean below."""
    def grouped(pos: str) -> str:
        return ('<m:groupChr><m:groupChrPr><m:chr m:val="→"/>'
                + pos + "</m:groupChrPr><m:e>" + r("abc")
                + "</m:e></m:groupChr>")

    assert to_latex(m(grouped('<m:pos m:val="top"/>'))) \
        == r"\overset{\to}{abc}"
    assert to_latex(m(grouped('<m:pos m:val="bot"/>'))) \
        == r"\underset{\to}{abc}"
    assert to_latex(m(grouped(""))) == r"\underset{\to}{abc}"


def test_a_BOXED_result_and_a_PHANTOM_spacer_keep_their_argument():
    """`borderBox` is how a paper highlights the result it wants read,
    and `phant` is how an author lines two rows up by hand. Both are one
    command and one braced argument, and dropping the argument leaves a
    command LaTeX will not compile."""
    box = "<m:borderBox><m:e>" + r("x=1") + "</m:e></m:borderBox>"
    phantom = "<m:phant><m:e>" + r("xy") + "</m:e></m:phant>"

    assert to_latex(m(box)) == r"\boxed{x=1}"
    assert to_latex(m(phantom)) == r"\phantom{xy}"


def test_a_run_styled_PLAIN_is_upright_the_same_as_one_marked_nor():
    """Two spellings of the same intent: `m:nor` and `sty="p"`. Word
    writes the second when the author set the style rather than the
    property, and a function name left in math italic is the error this
    prevents — `max` as m·a·x, three variables multiplied."""
    plain = '<m:r><m:rPr><m:sty m:val="p"/></m:rPr><m:t>max</m:t></m:r>'
    italic = '<m:r><m:rPr><m:sty m:val="i"/></m:rPr><m:t>max</m:t></m:r>'

    assert to_latex(m(plain)) == r"\text{max}"
    assert to_latex(m(italic)) == "max", "only 'p' is upright"


# --- the second to_latex round, from the 2026-08-19 measurement ---------
#
# Every construct below is one an author reaches through Word's equation
# editor rather than by typing LaTeX, and each was written by a branch
# nothing exercised: the hidden degree, the hidden limit, the separator
# inside a delimiter, an accent that is not a hat, a bar that hangs
# under. A wrong answer here is not a crash — it is a formula that reads
# as a different formula.


def test_a_DELIMITER_with_two_operands_keeps_its_separator():
    r"""`len(findall("e")) > 1`. One operand is a bracket, two are a
    set-builder or a conditional probability — `P(A|B)` — and the
    separator is what says which. With `>=` a plain bracket is joined
    with a `\middle|` it never had; the fixture needs BOTH shapes,
    because the one-operand case is what tells the two apart."""
    two = ('<m:d><m:dPr><m:sepChr m:val="|"/></m:dPr>'
           "<m:e>" + r("A") + "</m:e><m:e>" + r("B") + "</m:e></m:d>")
    one = "<m:d><m:e>" + r("x+y") + "</m:e></m:d>"

    assert to_latex(m(two)) == r"\left( A \middle| B \right)"
    assert to_latex(m(one)) == r"\left( x+y \right)"


def test_a_HIDDEN_limit_on_an_n_ary_is_not_written():
    r"""`sub.strip() and subHide != "1"` — both, and `or` in place of
    `and` writes a limit Word is deliberately not showing.

    Word keeps the text of a limit it hides, so the element is there
    with `subHide` beside it: an author who typed a sum, gave it limits
    and then chose "no limits" gets `\sum_{i=1}^{n}` back from an `or`,
    over a formula that shows none."""
    body = ('<m:nary><m:naryPr><m:chr m:val="∑"/>'
            '<m:subHide m:val="1"/><m:supHide m:val="1"/></m:naryPr>'
            "<m:sub>" + r("i=1") + "</m:sub><m:sup>" + r("n") + "</m:sup>"
            "<m:e>" + r("x") + "</m:e></m:nary>")

    assert to_latex(m(body)) == r"\sum {x}"


def test_a_HIDDEN_radical_degree_is_a_plain_square_root():
    r"""Word keeps the degree it is not showing, so `degHide` is the
    only thing that says a root is square: without this branch a
    hidden 2 comes back as `\sqrt[2]{x}`, which is the same value and a
    different formula on the page.

    (The `is` spelling of the comparison is EQUIVALENT here and is
    argued at the foot of the file — a one-character string is one
    object in CPython, whoever made it.)"""
    body = ('<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr>'
            "<m:deg>" + r("2") + "</m:deg><m:e>" + r("x") + "</m:e></m:rad>")

    assert to_latex(m(body)) == r"\sqrt{x}"


def test_a_BAR_hangs_under_unless_its_position_says_top():
    r"""`pos == "top"`, and `<=` reads "bot" as top — a mean over a
    variable, where the bar is the notation. Word writes `bot` and also
    omits the element, and both mean below."""
    def barred(pos: str) -> str:
        return ("<m:bar><m:barPr>" + pos + "</m:barPr><m:e>" + r("x")
                + "</m:e></m:bar>")

    assert to_latex(m(barred('<m:pos m:val="top"/>'))) == r"\overline{x}"
    assert to_latex(m(barred('<m:pos m:val="bot"/>'))) == r"\underline{x}"
    assert to_latex(m(barred(""))) == r"\underline{x}"


def test_a_grouping_character_ABOVE_the_brace_codepoints_is_not_a_brace():
    r"""`chr_ == "⏞"` against `>=`. The two brace characters are U+23DE
    and U+23DF, and every fixture here used a character BELOW them (an
    arrow at U+2192), where `>=` and `==` agree. An author's own glyph
    can sit anywhere — this one is a wave dash at U+301C — and above the
    braces the comparison silently promotes it to an overbrace."""
    body = ('<m:groupChr><m:groupChrPr><m:chr m:val="〜"/>'
            '<m:pos m:val="bot"/></m:groupChrPr>'
            "<m:e>" + r("abc") + "</m:e></m:groupChr>")

    assert to_latex(m(body)) == r"\underset{〜}{abc}"


def test_an_ACCENT_is_the_one_the_equation_carries():
    r"""`_ACCENTS.get(chr or "̂", ...)` — `or` supplies the DEFAULT hat
    when Word omits the character, and `and` turns every explicit accent
    into the default: a bar becomes a hat, and \bar{x} is a mean while
    \hat{x} is an estimate."""
    def accented(chr_: str) -> str:
        return ("<m:acc><m:accPr>" + chr_ + "</m:accPr><m:e>" + r("x")
                + "</m:e></m:acc>")

    assert to_latex(m(accented('<m:chr m:val="̄"/>'))) == r"\bar{x}"
    assert to_latex(m(accented('<m:chr m:val="⃗"/>'))) == r"\vec{x}"
    assert to_latex(m(accented(""))) == r"\hat{x}"


def test_an_unknown_element_whose_name_sorts_EARLY_is_still_reported():
    """`name == "ctrlPr"`, mutated to `<`: an element this converter
    does not know is meant to leave a visible marker and a gap. Under
    `<` every unknown name that sorts before "ctrlPr" is silently
    treated as a properties element instead — dropped from the formula
    AND from the gap report, which is the one thing `strict=True` has to
    be able to see."""
    out = to_latex(m("<m:box2>" + r("x") + "</m:box2>"))

    assert "[?m:box2]" in out and "x" in out
    with pytest.raises(ConversionGap, match="m:box2"):
        to_latex(m("<m:box2/>"), strict=True)


# --- what is left in the to_latex walk, and why -------------------------
#
# Three survivors from this round, each argued rather than tested:
#
#   `if hide == "1"` -> `is`. The value is a one-character string off an
#   XML attribute, and CPython hands out one object for every latin-1
#   character — measured: `etree.fromstring('<a val="1"/>').get("val")
#   is "1"` is True. The two spellings cannot disagree here. (They CAN
#   for a longer attribute value, which is why this is argued per site
#   rather than as a rule.)
#
#   `if len(el.findall("e")) > 1` -> `>= 1`, and -> `!= 1`. The branch
#   chooses between joining the operands with a separator and reading
#   the single one directly — and `" \middle| ".join([x])` IS `x`, so
#   the two paths agree for one operand and for none. The mutants pick
#   the other path to the same string.


def test_a_command_ENDING_in_a_brace_takes_no_guard_space():
    r"""`sym[-1].isalpha()` — the trailing space exists to stop `\le x`
    fusing into `\lex`, and a command that ends in `}` needs none:
    `\mathbb{R}` is complete, and the space after it is a space in the
    rendered formula.

    Every other symbol in the table ends in a letter, so `sym[1]` and
    `sym[-2]` answer the same question as `sym[-1]` — the blackboard
    letters are the six that tell them apart. The base sits at the END
    of the output, where `.strip()` would hide a trailing space, so the
    fixture puts a variable after it."""
    assert to_latex(m(r("ℝx"))) == r"\mathbb{R}x"
    assert to_latex(m(r("≤x"))) == r"\le x"


def test_the_math_alphanumeric_block_starts_at_its_FIRST_character():
    r"""`ord(ch) >= 0x1d400`. U+1D400 is MATHEMATICAL BOLD CAPITAL A —
    the first character of the block, and the one a bound off by one
    stops decomposing: it would come through as itself, and a paper's
    bold matrix name would be a glyph LaTeX has no font for.

    Below the block the guard must NOT fire, and `!=` in its place is
    the mutant that matters: U+210E PLANCK CONSTANT carries a `<font>`
    decomposition too, so the same branch would quietly rewrite it to a
    plain `h` — a different symbol, and one the author chose."""
    assert to_latex(m(r("\U0001d400"))) == "A"
    assert to_latex(m(r("\U0001d465"))) == "x"
    assert to_latex(m(r("ℎ"))) == "ℎ"
